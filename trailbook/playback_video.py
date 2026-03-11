import bisect
import glob
import io
import math
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.shortcuts import get_object_or_404
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import TrailEntry, TrailMoment, TrailPlaybackShareRequest


CANVAS_WIDTH = 720
CANVAS_HEIGHT = 1280
TILE_SIZE = 256
MERCATOR_MAX_LAT = 85.05112878
PLAYBACK_MIN_DURATION_MS = 9000
PLAYBACK_MAX_DURATION_MS = 26000
PLAYBACK_FRAME_MS = 120
PLAYBACK_FALLBACK_SPEED_MPS = 1.4
PLAYBACK_SEGMENT_MIN_MS = 180
PLAYBACK_SEGMENT_MAX_MS = 2200
PLAYBACK_MAP_TOP_DEFAULT = 130
PLAYBACK_MAP_TOP_SPLIT = int(CANVAS_HEIGHT * 0.75)


def _safe_seconds(value):
    try:
        return max(0.0, float(value))
    except Exception:
        return 0.0


def _safe_float(value):
    try:
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _haversine_meters(lat1, lng1, lat2, lng2):
    radius = 6371000.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * (math.sin(dlng / 2.0) ** 2)
    return radius * (2.0 * math.atan2(math.sqrt(a), math.sqrt(max(1e-12, 1.0 - a))))


def _resolve_point_speed_mps(from_point, to_point, distance_m, dt_ms):
    candidates = [
        _safe_float(to_point.get("speed")),
        _safe_float(from_point.get("speed")),
        (distance_m / (dt_ms / 1000.0)) if dt_ms > 0 else None,
    ]
    for value in candidates:
        if value is None or value < 0:
            continue
        return float(value)
    return PLAYBACK_FALLBACK_SPEED_MPS


def _movement_mode_from_speed(speed_mps):
    if not math.isfinite(speed_mps) or speed_mps < 0.6:
        return "standing"
    if speed_mps < 2.2:
        return "walking"
    if speed_mps < 4.8:
        return "running"
    if speed_mps < 11.2:
        return "biking"
    if speed_mps < 83.4:
        return "vehicle"
    return "flight"


def _build_app_style_playback_timeline(points):
    if len(points) < 2:
        source_point_secs = [_safe_seconds(item.get("sec")) for item in points]
        if source_point_secs and source_point_secs[-1] <= 0:
            source_point_secs[-1] = 1.0
        return {
            "segments": [],
            "source_point_secs": source_point_secs,
            "playback_point_secs": source_point_secs[:],
            "source_duration": max(0.0, source_point_secs[-1] if source_point_secs else 0.0),
            "playback_duration": max(0.0, source_point_secs[-1] if source_point_secs else 0.0),
        }

    source_point_secs = [_safe_seconds(item.get("sec")) for item in points]
    rough_duration_ms = _clamp(len(points) * 420, PLAYBACK_MIN_DURATION_MS, PLAYBACK_MAX_DURATION_MS)
    weighted_total = 0.0
    segments = []

    for idx in range(len(points) - 1):
        from_point = points[idx]
        to_point = points[idx + 1]
        distance_m = _haversine_meters(
            from_point["lat"],
            from_point["lng"],
            to_point["lat"],
            to_point["lng"],
        )
        dt_ms = max(0.0, (source_point_secs[idx + 1] - source_point_secs[idx]) * 1000.0)
        speed_mps = _resolve_point_speed_mps(
            from_point=from_point,
            to_point=to_point,
            distance_m=distance_m,
            dt_ms=dt_ms,
        )
        mode = _movement_mode_from_speed(speed_mps)
        weight = (distance_m / max(0.3, speed_mps)) if distance_m > 0.5 else 0.35
        weighted_total += weight
        segments.append(
            {
                "index": idx,
                "speed_mps": speed_mps,
                "mode": mode,
                "weight": weight,
                "duration_ms": 0,
                "source_start_sec": source_point_secs[idx],
                "source_end_sec": source_point_secs[idx + 1],
            }
        )

    safe_total = max(weighted_total, 1.0)
    used_duration_ms = 0
    playback_point_secs = [0.0]
    for idx, segment in enumerate(segments):
        is_last = idx == len(segments) - 1
        duration_ms = round((segment["weight"] / safe_total) * rough_duration_ms)
        duration_ms = _clamp(duration_ms, PLAYBACK_SEGMENT_MIN_MS, PLAYBACK_SEGMENT_MAX_MS)
        if is_last:
            duration_ms = max(PLAYBACK_SEGMENT_MIN_MS, rough_duration_ms - used_duration_ms)
        segment["duration_ms"] = duration_ms
        segment["playback_start_sec"] = playback_point_secs[-1]
        segment["playback_end_sec"] = playback_point_secs[-1] + (duration_ms / 1000.0)
        playback_point_secs.append(segment["playback_end_sec"])
        used_duration_ms += duration_ms

    source_duration = max(0.0, source_point_secs[-1] - source_point_secs[0])
    playback_duration = max(0.0, playback_point_secs[-1] - playback_point_secs[0])
    return {
        "segments": segments,
        "source_point_secs": source_point_secs,
        "playback_point_secs": playback_point_secs,
        "source_duration": source_duration,
        "playback_duration": playback_duration,
    }


def _map_source_sec_to_playback_sec(source_sec, source_point_secs, playback_point_secs):
    if not source_point_secs or not playback_point_secs:
        return 0.0
    if len(source_point_secs) == 1 or len(playback_point_secs) == 1:
        return _safe_seconds(playback_point_secs[0])
    source_sec = _safe_seconds(source_sec)
    if source_sec <= source_point_secs[0]:
        return playback_point_secs[0]
    if source_sec >= source_point_secs[-1]:
        return playback_point_secs[-1]
    right = bisect.bisect_right(source_point_secs, source_sec)
    left = max(0, right - 1)
    right = min(len(source_point_secs) - 1, right)
    start_source = source_point_secs[left]
    end_source = source_point_secs[right]
    if end_source <= start_source:
        return playback_point_secs[right]
    ratio = (source_sec - start_source) / (end_source - start_source)
    start_playback = playback_point_secs[left]
    end_playback = playback_point_secs[right]
    return start_playback + ((end_playback - start_playback) * ratio)


def _segment_for_playback_sec(segments, playback_sec):
    if not segments:
        return None
    for segment in segments:
        if playback_sec <= segment["playback_end_sec"]:
            return segment
    return segments[-1]


def _extract_geometry_points(trail):
    geometry = trail.path_geometry or {}
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    coordinates = geometry.get("coordinates") or []
    out = []
    for item in coordinates:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lng, lat = item[0], item[1]
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            out.append({"lat": float(lat), "lng": float(lng)})
    return out


def _trail_owner_display_name(trail):
    user = getattr(trail, "user", None)
    if user is None:
        return "Trail user"
    profile = getattr(user, "profile", None)
    profile_name = str(getattr(profile, "name", "") or "").strip()
    if profile_name:
        return profile_name
    username = str(getattr(user, "username", "") or "").strip()
    if username:
        return username
    email = str(getattr(user, "email", "") or "").strip()
    if email:
        return email.split("@")[0]
    return "Trail user"


def _trail_owner_avatar_path(trail):
    user = getattr(trail, "user", None)
    profile = getattr(user, "profile", None)
    image = getattr(profile, "profile_picture", None)
    if not image:
        return None
    try:
        return image.path
    except Exception:
        return None


def _trail_points_with_timeline(trail):
    ordered_points = list(
        trail.points.order_by("recorded_at", "id").values("lat", "lng", "recorded_at", "speed"),
    )
    if ordered_points:
        base_ts = ordered_points[0]["recorded_at"] or trail.start_time
        if base_ts is None:
            base_ts = trail.created_at
        points = []
        last_sec = 0.0
        for idx, item in enumerate(ordered_points):
            ts = item.get("recorded_at")
            sec = 0.0
            if ts and base_ts:
                sec = max(0.0, (ts - base_ts).total_seconds())
            if idx > 0 and sec <= last_sec:
                sec = last_sec + 0.35
            last_sec = sec
            points.append(
                {
                    "lat": float(item["lat"]),
                    "lng": float(item["lng"]),
                    "sec": sec,
                    "speed": _safe_float(item.get("speed")),
                }
            )
        return points, base_ts

    geometry_points = _extract_geometry_points(trail)
    if len(geometry_points) < 2:
        return [], trail.start_time or trail.created_at

    if trail.start_time and trail.end_time:
        total = max(1.0, (trail.end_time - trail.start_time).total_seconds())
        base_ts = trail.start_time
    else:
        total = max(1.0, float(len(geometry_points) - 1))
        base_ts = trail.start_time or trail.created_at

    step = total / max(1, len(geometry_points) - 1)
    points = []
    for idx, item in enumerate(geometry_points):
        points.append(
            {
                "lat": item["lat"],
                "lng": item["lng"],
                "sec": idx * step,
                "speed": None,
            }
        )
    return points, base_ts


def _moment_media_path(moment):
    media = getattr(moment, "media_file", None)
    if not media:
        return None
    try:
        return media.path
    except Exception:
        return None


def _load_moments(trail, base_ts):
    owner_name = _trail_owner_display_name(trail)
    owner_avatar_path = _trail_owner_avatar_path(trail)
    moments = []
    for moment in trail.moments.order_by("recorded_at", "id"):
        ts = moment.recorded_at or base_ts
        sec = 0.0
        if ts and base_ts:
            sec = max(0.0, (ts - base_ts).total_seconds())
        moments.append(
            {
                "id": moment.id,
                "moment_type": moment.moment_type,
                "caption": (moment.caption or "").strip(),
                "text": (moment.text or "").strip(),
                "lat": moment.lat,
                "lng": moment.lng,
                "sec": sec,
                "recorded_at": ts,
                "media_path": _moment_media_path(moment),
                "author_name": owner_name,
                "author_avatar_path": owner_avatar_path,
            }
        )
    return moments


def _compute_bounds(points, moments):
    lats = [item["lat"] for item in points if item.get("lat") is not None]
    lngs = [item["lng"] for item in points if item.get("lng") is not None]
    # Keep exported playback focused on the trail path itself.
    # Fall back to moment coordinates only when no point coordinates are available.
    if not lats or not lngs:
        for moment in moments:
            if moment.get("lat") is None or moment.get("lng") is None:
                continue
            lats.append(moment["lat"])
            lngs.append(moment["lng"])
    if not lats or not lngs:
        return (0.0, 0.0, 1.0, 1.0)
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    pad_factor = _safe_float(
        getattr(settings, "TRAILBOOK_PLAYBACK_MAP_PADDING_FACTOR", 0.03),
    )
    if pad_factor is None:
        pad_factor = 0.03
    pad_factor = _clamp(pad_factor, 0.01, 0.25)
    min_pad = _safe_float(
        getattr(settings, "TRAILBOOK_PLAYBACK_MAP_MIN_PAD_DEGREES", 0.00006),
    )
    if min_pad is None:
        min_pad = 0.00006
    min_pad = max(0.00005, min_pad)
    lat_pad = max((max_lat - min_lat) * pad_factor, min_pad)
    lng_pad = max((max_lng - min_lng) * pad_factor, min_pad)
    return (
        min_lat - lat_pad,
        max_lat + lat_pad,
        min_lng - lng_pad,
        max_lng + lng_pad,
    )


def _project_linear_fallback(lat, lng, bounds, rect):
    min_lat, max_lat, min_lng, max_lng = bounds
    left, top, right, bottom = rect
    w = max(1.0, right - left)
    h = max(1.0, bottom - top)
    x_ratio = 0.5 if math.isclose(max_lng, min_lng) else (lng - min_lng) / (max_lng - min_lng)
    y_ratio = 0.5 if math.isclose(max_lat, min_lat) else (max_lat - lat) / (max_lat - min_lat)
    x = left + min(max(x_ratio, 0.0), 1.0) * w
    y = top + min(max(y_ratio, 0.0), 1.0) * h
    return (x, y)


def _clamp_lat(lat):
    return max(-MERCATOR_MAX_LAT, min(MERCATOR_MAX_LAT, float(lat)))


def _mercator_world_px(lat, lng, zoom):
    lat = _clamp_lat(lat)
    lng = float(lng)
    map_size = TILE_SIZE * (2**zoom)
    x = (lng + 180.0) / 360.0 * map_size
    sin_lat = math.sin(math.radians(lat))
    y = (
        0.5
        - (math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi))
    ) * map_size
    return x, y


def _choose_map_zoom(bounds, width, height):
    min_lat, max_lat, min_lng, max_lng = bounds
    fit_ratio = _safe_float(
        getattr(settings, "TRAILBOOK_PLAYBACK_MAP_FIT_RATIO", 0.99),
    )
    if fit_ratio is None:
        fit_ratio = 0.99
    fit_ratio = _clamp(fit_ratio, 0.72, 0.99)
    usable_w = max(80, int(width * fit_ratio))
    usable_h = max(80, int(height * fit_ratio))

    for zoom in range(19, 1, -1):
        x0, y0 = _mercator_world_px(min_lat, min_lng, zoom)
        x1, y1 = _mercator_world_px(max_lat, max_lng, zoom)
        span_x = abs(x1 - x0)
        span_y = abs(y1 - y0)
        if span_x <= usable_w and span_y <= usable_h:
            return zoom
    return 2


def _tile_url_template():
    return getattr(
        settings,
        "TRAILBOOK_MAP_TILE_URL_TEMPLATE",
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    )


def _tile_user_agent():
    return getattr(settings, "TRAILBOOK_MAP_TILE_USER_AGENT", "Meetrail/1.0")


def _tile_timeout_seconds():
    return float(getattr(settings, "TRAILBOOK_MAP_TILE_TIMEOUT_SECONDS", 3.0))


def _load_map_tile(zoom, tile_x, tile_y, cache_dir):
    max_index = (2**zoom) - 1
    wrapped_x = tile_x % (2**zoom)
    if tile_y < 0 or tile_y > max_index:
        # Outside valid Mercator tile range.
        return Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#eef2f7"), False

    cache_name = f"z{zoom}_x{wrapped_x}_y{tile_y}.png"
    cache_path = os.path.join(cache_dir, cache_name)
    if os.path.exists(cache_path):
        try:
            with Image.open(cache_path) as img:
                return img.convert("RGB"), True
        except Exception:
            pass

    tile_url = _tile_url_template().format(z=zoom, x=wrapped_x, y=tile_y)
    req = Request(
        tile_url,
        headers={"User-Agent": _tile_user_agent()},
    )
    try:
        with urlopen(req, timeout=_tile_timeout_seconds()) as response:
            content = response.read()
        image = Image.open(io.BytesIO(content)).convert("RGB")
        try:
            image.save(cache_path, "PNG")
        except Exception:
            pass
        return image, True
    except (URLError, OSError, ValueError):
        return Image.new("RGB", (TILE_SIZE, TILE_SIZE), "#eef2f7"), False


def _build_map_context(bounds, width, height, center_lat, center_lng, zoom, cache_dir):
    center_x, center_y = _mercator_world_px(center_lat, center_lng, zoom)
    left_px = center_x - (width / 2.0)
    top_px = center_y - (height / 2.0)
    right_px = left_px + width
    bottom_px = top_px + height

    tile_x_start = int(math.floor(left_px / TILE_SIZE))
    tile_x_end = int(math.floor((right_px - 1) / TILE_SIZE))
    tile_y_start = int(math.floor(top_px / TILE_SIZE))
    tile_y_end = int(math.floor((bottom_px - 1) / TILE_SIZE))

    image = Image.new("RGB", (width, height), "#e5e7eb")
    used_any_network_tile = False

    for tx in range(tile_x_start, tile_x_end + 1):
        for ty in range(tile_y_start, tile_y_end + 1):
            tile, has_real_tile = _load_map_tile(zoom, tx, ty, cache_dir)
            if has_real_tile:
                used_any_network_tile = True
            offset_x = int(round((tx * TILE_SIZE) - left_px))
            offset_y = int(round((ty * TILE_SIZE) - top_px))
            image.paste(tile, (offset_x, offset_y))

    return {
        "image": image,
        "zoom": zoom,
        "left_px": left_px,
        "top_px": top_px,
        "has_tiles": used_any_network_tile,
        "bounds": bounds,
    }


def _project_on_map(lat, lng, map_context, rect):
    px, py = _mercator_world_px(lat, lng, map_context["zoom"])
    local_x = px - map_context["left_px"]
    local_y = py - map_context["top_px"]
    left, top, _, _ = rect
    return (left + local_x, top + local_y)


def _interpolate_position(point_secs, points, sec):
    if not points:
        return None, 0
    if len(points) == 1:
        return points[0], 0
    if sec <= point_secs[0]:
        return points[0], 0
    if sec >= point_secs[-1]:
        return points[-1], len(points) - 1

    right = bisect.bisect_right(point_secs, sec)
    left = max(0, right - 1)
    right = min(len(points) - 1, right)
    t0 = point_secs[left]
    t1 = point_secs[right]
    if t1 <= t0:
        return points[right], right
    ratio = (sec - t0) / (t1 - t0)
    lat = points[left]["lat"] + (points[right]["lat"] - points[left]["lat"]) * ratio
    lng = points[left]["lng"] + (points[right]["lng"] - points[left]["lng"]) * ratio
    return {"lat": lat, "lng": lng}, left


def _format_time_label(sec):
    sec = int(max(0, sec))
    hh = sec // 3600
    mm = (sec % 3600) // 60
    ss = sec % 60
    if hh:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


def _extract_video_thumbnail(video_path, target_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0.2",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        target_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _extract_video_clip_frames(
    video_path,
    frame_pattern,
    fps,
    clip_seconds,
    width,
    height,
):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-i",
        video_path,
        "-t",
        f"{max(1.0, float(clip_seconds)):.2f}",
        "-vf",
        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "-q:v",
        "3",
        frame_pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(glob.glob(frame_pattern.replace("%05d", "*")))


def _build_moment_media_cache(moments, panel_size, temp_dir, fps, video_clip_seconds):
    out = {}
    width, height = panel_size
    for moment in moments:
        media_path = moment.get("media_path")
        if not media_path or not os.path.exists(media_path):
            continue
        try:
            if moment["moment_type"] == TrailMoment.TYPE_PHOTO:
                with Image.open(media_path) as src:
                    frame = ImageOps.fit(
                        src.convert("RGB"),
                        (width, height),
                        method=Image.Resampling.LANCZOS,
                    )
                out[moment["id"]] = {
                    "kind": "image",
                    "image": frame,
                    "duration_seconds": None,
                }
                continue
            if moment["moment_type"] == TrailMoment.TYPE_VIDEO:
                frame_pattern = os.path.join(
                    temp_dir,
                    f"moment_video_{moment['id']}_%05d.jpg",
                )
                frame_paths = _extract_video_clip_frames(
                    video_path=media_path,
                    frame_pattern=frame_pattern,
                    fps=fps,
                    clip_seconds=video_clip_seconds,
                    width=width,
                    height=height,
                )
                if frame_paths:
                    out[moment["id"]] = {
                        "kind": "video",
                        "frames": frame_paths,
                        "duration_seconds": len(frame_paths) / float(max(1, fps)),
                    }
                    continue
                thumb_path = os.path.join(temp_dir, f"moment_video_{moment['id']}.jpg")
                _extract_video_thumbnail(media_path, thumb_path)
                with Image.open(thumb_path) as src:
                    frame = ImageOps.fit(
                        src.convert("RGB"),
                        (width, height),
                        method=Image.Resampling.LANCZOS,
                    )
                out[moment["id"]] = {
                    "kind": "image",
                    "image": frame,
                    "duration_seconds": None,
                }
        except Exception:
            # Keep rendering resilient even if one media file is unreadable.
            continue
    return out


def _build_avatar_cache(moments, avatar_size):
    cache = {}
    target_size = (avatar_size, avatar_size)
    for moment in moments:
        path = moment.get("author_avatar_path")
        if not path or path in cache:
            continue
        if not os.path.exists(path):
            continue
        try:
            with Image.open(path) as src:
                avatar = ImageOps.fit(
                    src.convert("RGB"),
                    target_size,
                    method=Image.Resampling.LANCZOS,
                )
            cache[path] = avatar
        except Exception:
            continue
    return cache


def _paste_circle_image(image, avatar, center_x, center_y, diameter):
    left = int(round(center_x - (diameter / 2.0)))
    top = int(round(center_y - (diameter / 2.0)))
    resized = ImageOps.fit(
        avatar.convert("RGB"),
        (diameter, diameter),
        method=Image.Resampling.LANCZOS,
    )
    mask = Image.new("L", (diameter, diameter), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    image.paste(resized.convert("RGBA"), (left, top), mask)


def _wrap_text_lines(draw, text, font, max_width, max_lines):
    words = [item for item in str(text or "").split() if item]
    if not words:
        return []
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        test_width = max(1, bbox[2] - bbox[0])
        if current and test_width > max_width:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) >= max_lines - 1:
                break
        else:
            current.append(word)
    if current and len(lines) < max_lines:
        lines.append(" ".join(current))
    if len(lines) == max_lines and len(words) > 1:
        last = lines[-1]
        if len(last) > 3 and not last.endswith("..."):
            lines[-1] = f"{last[: max(1, len(last) - 3)]}..."
    return lines


def _moment_marker_style(moment_type):
    kind = str(moment_type or "")
    if kind == TrailMoment.TYPE_VIDEO:
        return "#ef4444"
    if kind == TrailMoment.TYPE_PHOTO:
        return "#06b6d4"
    if kind in {TrailMoment.TYPE_NOTE, TrailMoment.TYPE_COMMENT}:
        return "#f59e0b"
    return "#7c3aed"


def _build_moment_markers(moments):
    grouped = {}
    for moment in moments:
        lat = _safe_float(moment.get("lat"))
        lng = _safe_float(moment.get("lng"))
        if lat is None or lng is None:
            continue
        key = (round(lat, 5), round(lng, 5))
        row = grouped.get(key)
        if row is None:
            grouped[key] = {
                "lat": lat,
                "lng": lng,
                "count": 1,
                "moment_type": moment.get("moment_type"),
            }
        else:
            row["count"] += 1
    return list(grouped.values())


def _moment_hold_duration(moment, media_cache, photo_hold_seconds, text_hold_seconds):
    kind = str(moment.get("moment_type") or "")
    if kind == TrailMoment.TYPE_VIDEO:
        entry = media_cache.get(moment.get("id")) or {}
        duration = entry.get("duration_seconds")
        if isinstance(duration, (int, float)) and duration > 0:
            return max(1.2, float(duration))
        return max(2.0, float(photo_hold_seconds))
    if kind == TrailMoment.TYPE_PHOTO:
        return max(1.0, float(photo_hold_seconds))
    return max(1.0, float(text_hold_seconds))


def _build_playback_pause_timeline(
    base_duration,
    moments,
    media_cache,
    photo_hold_seconds,
    text_hold_seconds,
):
    eligible = []
    for moment in moments:
        moment_type = str(moment.get("moment_type") or "")
        has_media = bool(media_cache.get(moment.get("id")))
        has_text = bool((moment.get("caption") or "").strip() or (moment.get("text") or "").strip())
        if moment_type == TrailMoment.TYPE_VIDEO and not has_media:
            continue
        if moment_type == TrailMoment.TYPE_PHOTO and not has_media:
            continue
        if moment_type not in {
            TrailMoment.TYPE_VIDEO,
            TrailMoment.TYPE_PHOTO,
            TrailMoment.TYPE_NOTE,
            TrailMoment.TYPE_COMMENT,
        }:
            continue
        if moment_type in {TrailMoment.TYPE_NOTE, TrailMoment.TYPE_COMMENT} and not has_text:
            continue
        hold_seconds = _moment_hold_duration(
            moment=moment,
            media_cache=media_cache,
            photo_hold_seconds=photo_hold_seconds,
            text_hold_seconds=text_hold_seconds,
        )
        if hold_seconds <= 0:
            continue
        eligible.append(
            {
                "moment": moment,
                "base_sec": _clamp(_safe_seconds(moment.get("playback_sec")), 0.0, max(0.0, float(base_duration))),
                "hold_seconds": hold_seconds,
            }
        )

    eligible.sort(
        key=lambda item: (
            item["base_sec"],
            _safe_seconds((item["moment"] or {}).get("playback_sec")),
            int((item["moment"] or {}).get("id") or 0),
        )
    )

    intervals = []
    output_sec = 0.0
    base_sec = 0.0
    for event in eligible:
        event_base = max(base_sec, min(base_duration, event["base_sec"]))
        move_delta = max(0.0, event_base - base_sec)
        if move_delta > 0:
            intervals.append(
                {
                    "kind": "move",
                    "output_start": output_sec,
                    "output_end": output_sec + move_delta,
                    "base_start": base_sec,
                    "base_end": event_base,
                    "moment": None,
                }
            )
            output_sec += move_delta
            base_sec = event_base

        hold = max(0.1, float(event["hold_seconds"]))
        intervals.append(
            {
                "kind": "pause",
                "output_start": output_sec,
                "output_end": output_sec + hold,
                "base_start": base_sec,
                "base_end": base_sec,
                "moment": event["moment"],
            }
        )
        output_sec += hold

    tail_move = max(0.0, base_duration - base_sec)
    if tail_move > 0:
        intervals.append(
            {
                "kind": "move",
                "output_start": output_sec,
                "output_end": output_sec + tail_move,
                "base_start": base_sec,
                "base_end": base_duration,
                "moment": None,
            }
        )
        output_sec += tail_move

    return {
        "intervals": intervals,
        "output_duration": max(0.0, output_sec),
    }


def _resolve_output_state(interval, output_sec):
    if not interval:
        return 0.0, None, 0.0
    start_output = _safe_seconds(interval.get("output_start"))
    end_output = _safe_seconds(interval.get("output_end"))
    if interval.get("kind") == "pause":
        elapsed = max(0.0, output_sec - start_output)
        return (
            _safe_seconds(interval.get("base_start")),
            interval.get("moment"),
            elapsed,
        )
    span_output = max(1e-6, end_output - start_output)
    ratio = _clamp((output_sec - start_output) / span_output, 0.0, 1.0)
    base_start = _safe_seconds(interval.get("base_start"))
    base_end = _safe_seconds(interval.get("base_end"))
    base_sec = base_start + ((base_end - base_start) * ratio)
    return base_sec, None, 0.0


def _resolve_active_moment_image(
    active_moment,
    media_cache,
    elapsed_in_moment,
    fps,
    panel_size,
):
    panel_w, panel_h = panel_size
    entry = media_cache.get(active_moment.get("id")) or {}
    if entry.get("kind") == "image" and entry.get("image") is not None:
        return entry["image"]
    if entry.get("kind") == "video":
        frames = entry.get("frames") or []
        if frames:
            index = min(
                len(frames) - 1,
                max(0, int(max(0.0, elapsed_in_moment) * max(1, fps))),
            )
            frame_path = frames[index]
            try:
                with Image.open(frame_path) as src:
                    return src.convert("RGB")
            except Exception:
                pass
    return Image.new("RGB", (panel_w, panel_h), "#111827")


def _load_font(size, bold=False):
    font_names = []
    if bold:
        font_names.extend(
            [
                "DejaVuSans-Bold.ttf",
                "Arial Bold.ttf",
                "Arial.ttf",
            ]
        )
    else:
        font_names.extend(
            [
                "DejaVuSans.ttf",
                "Arial.ttf",
            ]
        )
    pil_font_dir = os.path.join(os.path.dirname(ImageFont.__file__), "fonts")
    for name in font_names:
        candidates = [
            name,
            os.path.join(pil_font_dir, name),
            os.path.join("/Library/Fonts", name),
            os.path.join("/System/Library/Fonts", name),
            os.path.join("/usr/share/fonts/truetype/dejavu", name),
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _active_moment_layout(map_rect):
    panel_top = 148
    panel_bottom = max(panel_top + 180, map_rect[1] - 14)
    panel_rect = (20, panel_top, CANVAS_WIDTH - 20, panel_bottom)
    media_rect = (
        panel_rect[0] + 18,
        panel_rect[1] + 42,
        panel_rect[2] - 18,
        panel_rect[3] - 18,
    )
    return panel_rect, media_rect


def _draw_active_moment(
    draw,
    image,
    active_moment,
    media_cache,
    avatar_cache,
    font,
    small_font,
    tiny_font,
    active_moment_offset,
    fps,
    map_rect,
):
    panel_rect, media_rect = _active_moment_layout(map_rect)
    panel_shadow_rect = (
        panel_rect[0] + 4,
        panel_rect[1] + 4,
        panel_rect[2] + 4,
        panel_rect[3] + 4,
    )
    draw.rounded_rectangle(panel_shadow_rect, radius=26, fill=(15, 23, 42, 130))
    draw.rounded_rectangle(
        panel_rect,
        radius=24,
        fill=(17, 24, 39, 235),
        outline=(196, 181, 253, 205),
        width=2,
    )
    draw.rounded_rectangle(
        (
            panel_rect[0] + 16,
            panel_rect[1] + 10,
            panel_rect[0] + 196,
            panel_rect[1] + 36,
        ),
        radius=11,
        fill=(124, 58, 237, 230),
    )
    draw.text((panel_rect[0] + 26, panel_rect[1] + 17), "Moment highlight", fill="#f5f3ff", font=tiny_font)

    panel_w = media_rect[2] - media_rect[0]
    panel_h = media_rect[3] - media_rect[1]
    kind = active_moment["moment_type"].capitalize()
    is_text_moment = active_moment.get("moment_type") in {TrailMoment.TYPE_NOTE, TrailMoment.TYPE_COMMENT}

    if is_text_moment:
        draw.rounded_rectangle(media_rect, radius=18, fill=(30, 41, 59, 238), outline=(255, 255, 255, 170), width=2)
        center_x = int(round((media_rect[0] + media_rect[2]) / 2.0))
        avatar_size = 92
        avatar_center_y = media_rect[1] + 66
        draw.ellipse(
            (
                center_x - (avatar_size // 2) - 4,
                avatar_center_y - (avatar_size // 2) - 4,
                center_x + (avatar_size // 2) + 4,
                avatar_center_y + (avatar_size // 2) + 4,
            ),
            fill=(124, 58, 237, 210),
        )
        avatar_path = active_moment.get("author_avatar_path")
        avatar_image = avatar_cache.get(avatar_path) if avatar_path else None
        if avatar_image is not None:
            _paste_circle_image(image, avatar_image, center_x, avatar_center_y, avatar_size)
        else:
            draw.ellipse(
                (
                    center_x - (avatar_size // 2),
                    avatar_center_y - (avatar_size // 2),
                    center_x + (avatar_size // 2),
                    avatar_center_y + (avatar_size // 2),
                ),
                fill=(15, 23, 42, 255),
                outline=(255, 255, 255, 180),
                width=2,
            )
        author_name = str(active_moment.get("author_name") or "Trail user").strip()[:32]
        author_bbox = draw.textbbox((0, 0), author_name, font=tiny_font)
        author_width = max(1, author_bbox[2] - author_bbox[0])
        draw.text((center_x - (author_width / 2.0), avatar_center_y + 58), author_name, fill="#ddd6fe", font=tiny_font)

        text_value = str(active_moment.get("text") or active_moment.get("caption") or "").strip()
        lines = _wrap_text_lines(
            draw=draw,
            text=text_value,
            font=small_font,
            max_width=max(80, panel_w - 92),
            max_lines=5,
        )
        if not lines:
            lines = ["Moment note"]
        line_height = 36
        text_top = avatar_center_y + 112
        max_text_top = media_rect[3] - (line_height * len(lines)) - 24
        text_top = min(text_top, max_text_top)
        text_top = max(text_top, media_rect[1] + 150)
        for idx, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=small_font)
            line_width = max(1, bbox[2] - bbox[0])
            line_x = center_x - (line_width / 2.0)
            line_y = text_top + (idx * line_height)
            draw.text((line_x, line_y), line, fill="#f8fafc", font=small_font)
        draw.text((media_rect[0] + 18, media_rect[3] - 30), f"{kind} moment", fill="#c4b5fd", font=tiny_font)
        return

    media_to_paste = _resolve_active_moment_image(
        active_moment=active_moment,
        media_cache=media_cache,
        elapsed_in_moment=active_moment_offset,
        fps=fps,
        panel_size=(panel_w, panel_h),
    )
    image.paste(media_to_paste.convert("RGBA"), (media_rect[0], media_rect[1]))
    draw.rounded_rectangle(media_rect, radius=14, outline=(255, 255, 255, 170), width=2)

    caption = (active_moment.get("caption") or active_moment.get("text") or f"{kind} moment").strip()
    caption = caption[:90]
    overlay_rect = (
        media_rect[0] + 10,
        max(media_rect[1] + 12, media_rect[3] - 88),
        media_rect[2] - 10,
        media_rect[3] - 10,
    )
    draw.rounded_rectangle(overlay_rect, radius=12, fill=(15, 23, 42, 195))
    draw.text((overlay_rect[0] + 14, overlay_rect[1] + 10), f"{kind} moment", fill="#f9fafb", font=font)
    draw.text((overlay_rect[0] + 14, overlay_rect[1] + 42), caption, fill="#e5e7eb", font=tiny_font)


def _render_frame(
    motion_sec,
    display_sec,
    playback_duration,
    points,
    point_secs,
    bounds,
    map_context_default,
    map_context_split,
    moment_markers,
    playback_segment,
    active_moment,
    media_cache,
    avatar_cache,
    font,
    small_font,
    tiny_font,
    watermark_font,
    active_moment_offset,
    fps,
):
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (238, 242, 255, 255))
    draw = ImageDraw.Draw(image)

    map_top = PLAYBACK_MAP_TOP_SPLIT if active_moment else PLAYBACK_MAP_TOP_DEFAULT
    map_rect = (28, map_top, CANVAS_WIDTH - 28, CANVAS_HEIGHT - 46)
    map_width = int(max(1, map_rect[2] - map_rect[0]))
    map_height = int(max(1, map_rect[3] - map_rect[1]))
    map_context = map_context_split if active_moment else map_context_default
    map_surface = map_context["image"] if map_context else Image.new("RGB", (map_width, map_height), "#e5e7eb")

    shadow_rect = (
        map_rect[0] + 4,
        map_rect[1] + 5,
        map_rect[2] + 4,
        map_rect[3] + 6,
    )
    draw.rounded_rectangle(shadow_rect, radius=26, fill=(15, 23, 42, 95))

    rounded_mask = Image.new("L", (map_width, map_height), 0)
    rounded_draw = ImageDraw.Draw(rounded_mask)
    rounded_draw.rounded_rectangle(
        (0, 0, map_width - 1, map_height - 1),
        radius=24,
        fill=255,
    )
    image.paste(map_surface.convert("RGBA"), (map_rect[0], map_rect[1]), rounded_mask)
    draw.rounded_rectangle(
        (
            map_rect[0] - 2,
            map_rect[1] - 2,
            map_rect[2] + 2,
            map_rect[3] + 2,
        ),
        radius=26,
        outline=(30, 41, 59, 120),
        width=2,
    )
    draw.rounded_rectangle(
        map_rect,
        radius=24,
        outline=(196, 181, 253, 235),
        width=2,
    )

    current, segment_idx = _interpolate_position(point_secs, points, motion_sec)

    def project_point(lat, lng):
        if map_context:
            return _project_on_map(lat, lng, map_context, map_rect)
        return _project_linear_fallback(lat, lng, bounds, map_rect)

    projected_all = [project_point(item["lat"], item["lng"]) for item in points]

    if len(projected_all) >= 2:
        draw.line(projected_all, fill=(196, 181, 253, 190), width=13, joint="curve")
        traversed = projected_all[: segment_idx + 1]
        if current:
            traversed.append(project_point(current["lat"], current["lng"]))
        if len(traversed) >= 2:
            draw.line(traversed, fill=(109, 40, 217, 240), width=9, joint="curve")

    for marker in moment_markers or []:
        marker_lat = _safe_float(marker.get("lat"))
        marker_lng = _safe_float(marker.get("lng"))
        if marker_lat is None or marker_lng is None:
            continue
        mx, my = project_point(marker_lat, marker_lng)
        count = max(1, int(marker.get("count") or 1))
        marker_color = _moment_marker_style(marker.get("moment_type"))
        radius = 6 if count == 1 else 8
        draw.ellipse(
            (mx - (radius + 3), my - (radius + 3), mx + (radius + 3), my + (radius + 3)),
            fill=(255, 255, 255, 150),
        )
        draw.ellipse(
            (mx - radius, my - radius, mx + radius, my + radius),
            fill=marker_color,
            outline="#ffffff",
            width=2,
        )
        if count > 1:
            bubble_r = 9
            bubble_x = mx + radius + 6
            bubble_y = my - radius - 5
            draw.ellipse(
                (
                    bubble_x - bubble_r,
                    bubble_y - bubble_r,
                    bubble_x + bubble_r,
                    bubble_y + bubble_r,
                ),
                fill=(15, 23, 42, 228),
                outline="#ffffff",
                width=1,
            )
            count_text = str(min(99, count))
            count_bbox = draw.textbbox((0, 0), count_text, font=tiny_font)
            count_w = max(1, count_bbox[2] - count_bbox[0])
            count_h = max(1, count_bbox[3] - count_bbox[1])
            draw.text(
                (bubble_x - (count_w / 2.0), bubble_y - (count_h / 2.0) - 1),
                count_text,
                fill="#ffffff",
                font=tiny_font,
            )

    if projected_all:
        sx, sy = projected_all[0]
        ex, ey = projected_all[-1]
        draw.ellipse((sx - 12, sy - 12, sx + 12, sy + 12), fill=(34, 197, 94, 95))
        draw.ellipse((sx - 8, sy - 8, sx + 8, sy + 8), fill="#22c55e", outline="#ffffff", width=2)
        draw.ellipse((ex - 12, ey - 12, ex + 12, ey + 12), fill=(249, 115, 22, 95))
        draw.ellipse((ex - 8, ey - 8, ex + 8, ey + 8), fill="#f97316", outline="#ffffff", width=2)

    if current:
        cx, cy = project_point(current["lat"], current["lng"])
        draw.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), fill=(37, 99, 235, 75))
        draw.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill="#2563eb", outline="#ffffff", width=3)

    elapsed = _format_time_label(display_sec)
    total = _format_time_label(playback_duration)
    progress_ratio = min(1.0, max(0.0, display_sec / max(0.001, playback_duration)))
    movement_mode = (playback_segment or {}).get("mode") or "walking"
    movement_speed = _safe_float((playback_segment or {}).get("speed_mps"))
    if movement_speed is None:
        speed_label = "-"
    else:
        speed_label = f"{movement_speed * 3.6:.1f} km/h"
    movement_label = movement_mode.capitalize()
    badge_rect = (28, 34, 428, 134)
    draw.rounded_rectangle(
        (
            badge_rect[0] + 2,
            badge_rect[1] + 3,
            badge_rect[2] + 2,
            badge_rect[3] + 3,
        ),
        radius=20,
        fill=(15, 23, 42, 110),
    )
    draw.rounded_rectangle(
        badge_rect,
        radius=20,
        fill=(17, 24, 39, 225),
        outline=(196, 181, 253, 215),
        width=2,
    )
    draw.text((44, 48), "MEETRAIL TRAIL PLAYBACK", fill="#e5e7eb", font=tiny_font)
    draw.text((44, 72), f"{elapsed} / {total}", fill="#f9fafb", font=small_font)
    draw.text((44, 99), f"{movement_label} • {speed_label}", fill="#ddd6fe", font=tiny_font)
    bar_left = 44
    bar_right = 386
    bar_top = 116
    bar_bottom = 126
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_right, bar_bottom),
        radius=6,
        fill=(255, 255, 255, 65),
    )
    bar_fill_right = bar_left + int((bar_right - bar_left) * progress_ratio)
    if bar_fill_right > bar_left:
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_fill_right, bar_bottom),
            radius=6,
            fill=(168, 85, 247, 235),
        )
    draw.text((394, 103), f"{int(round(progress_ratio * 100))}%", fill="#e9d5ff", font=tiny_font)

    if active_moment:
        _draw_active_moment(
            draw=draw,
            image=image,
            active_moment=active_moment,
            media_cache=media_cache,
            avatar_cache=avatar_cache,
            font=font,
            small_font=small_font,
            tiny_font=tiny_font,
            active_moment_offset=active_moment_offset,
            fps=fps,
            map_rect=map_rect,
        )

    watermark_text = "MEETRAIL"
    watermark_subtext = "trail playback"
    watermark_bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
    watermark_sub_bbox = draw.textbbox((0, 0), watermark_subtext, font=tiny_font)
    watermark_w = max(1, watermark_bbox[2] - watermark_bbox[0])
    watermark_h = max(1, watermark_bbox[3] - watermark_bbox[1])
    watermark_sub_w = max(1, watermark_sub_bbox[2] - watermark_sub_bbox[0])
    watermark_sub_h = max(1, watermark_sub_bbox[3] - watermark_sub_bbox[1])
    watermark_pad_x = 18
    watermark_pad_y = 10
    watermark_inner_h = watermark_h + watermark_sub_h + 6
    watermark_inner_w = max(watermark_w, watermark_sub_w)
    watermark_right = CANVAS_WIDTH - 18
    watermark_bottom = CANVAS_HEIGHT - 16
    watermark_left = watermark_right - watermark_inner_w - (watermark_pad_x * 2)
    watermark_top = watermark_bottom - watermark_inner_h - (watermark_pad_y * 2)
    draw.rounded_rectangle(
        (
            watermark_left + 2,
            watermark_top + 3,
            watermark_right + 2,
            watermark_bottom + 3,
        ),
        radius=14,
        fill=(15, 23, 42, 130),
    )
    draw.rounded_rectangle(
        (watermark_left, watermark_top, watermark_right, watermark_bottom),
        radius=14,
        fill=(17, 24, 39, 220),
        outline=(196, 181, 253, 190),
        width=2,
    )
    draw.text(
        (watermark_left + watermark_pad_x, watermark_top + watermark_pad_y),
        watermark_text,
        fill="#f9fafb",
        font=watermark_font,
    )
    draw.text(
        (
            watermark_left + watermark_pad_x,
            watermark_top + watermark_pad_y + watermark_h + 2,
        ),
        watermark_subtext,
        fill="#ddd6fe",
        font=tiny_font,
    )

    return image.convert("RGB")


def render_playback_share_request_video(playback_request_id, progress_callback=None):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed on the backend server.")

    request = get_object_or_404(
        TrailPlaybackShareRequest.objects.select_related("trail").prefetch_related(
            "trail__points",
            "trail__moments",
        ),
        id=playback_request_id,
    )
    trail = request.trail
    if trail.status != TrailEntry.STATUS_COMPLETED:
        raise RuntimeError("Trail must be completed before playback can be rendered.")

    points, base_ts = _trail_points_with_timeline(trail)
    if len(points) < 2:
        raise RuntimeError("Not enough trail points to render playback.")

    playback_timeline = _build_app_style_playback_timeline(points)
    source_point_secs = playback_timeline["source_point_secs"]
    playback_point_secs = playback_timeline["playback_point_secs"]
    playback_segments = playback_timeline["segments"]
    source_duration = max(0.0, float(playback_timeline["source_duration"]))
    movement_duration = max(2.0, float(playback_timeline["playback_duration"]))
    output_duration = movement_duration

    fps = max(4, int(getattr(settings, "TRAILBOOK_PLAYBACK_FPS", 8)))
    max_seconds = max(30, int(getattr(settings, "TRAILBOOK_PLAYBACK_MAX_SECONDS", 900)))
    max_frames = max(120, int(getattr(settings, "TRAILBOOK_PLAYBACK_MAX_FRAMES", 7200)))

    moments = _load_moments(trail, base_ts)
    bounds = _compute_bounds(points, moments)
    draw_font = _load_font(22, bold=True)
    small_font = _load_font(28, bold=True)
    tiny_font = _load_font(16, bold=False)
    watermark_font = _load_font(34, bold=True)

    moment_video_clip_seconds = max(
        3.0,
        float(getattr(settings, "TRAILBOOK_PLAYBACK_VIDEO_MAX_SECONDS", 8.0)),
    )
    photo_hold_seconds = max(
        1.2,
        float(getattr(settings, "TRAILBOOK_PLAYBACK_PHOTO_HOLD_SECONDS", 3.0)),
    )
    text_hold_seconds = max(
        1.2,
        float(getattr(settings, "TRAILBOOK_PLAYBACK_TEXT_HOLD_SECONDS", 2.8)),
    )

    output_fd, output_path = tempfile.mkstemp(prefix="trailbook_playback_", suffix=".mp4")
    os.close(output_fd)

    if progress_callback:
        progress_callback(10, "Preparing playback timeline")

    with tempfile.TemporaryDirectory(prefix="trailbook_frames_") as frame_dir:
        if progress_callback:
            progress_callback(14, "Loading map tiles")

        map_width = CANVAS_WIDTH - 56
        map_height_default = CANVAS_HEIGHT - 46 - PLAYBACK_MAP_TOP_DEFAULT
        map_height_split = CANVAS_HEIGHT - 46 - PLAYBACK_MAP_TOP_SPLIT
        center_lat = (bounds[0] + bounds[1]) / 2.0
        center_lng = (bounds[2] + bounds[3]) / 2.0
        zoom = _choose_map_zoom(bounds, map_width, map_height_default)
        tile_cache_dir = os.path.join(frame_dir, "tile_cache")
        os.makedirs(tile_cache_dir, exist_ok=True)
        map_context_default = _build_map_context(
            bounds=bounds,
            width=map_width,
            height=map_height_default,
            center_lat=center_lat,
            center_lng=center_lng,
            zoom=zoom,
            cache_dir=tile_cache_dir,
        )
        map_context_split = _build_map_context(
            bounds=bounds,
            width=map_width,
            height=map_height_split,
            center_lat=center_lat,
            center_lng=center_lng,
            zoom=zoom,
            cache_dir=tile_cache_dir,
        )
        split_map_rect = (28, PLAYBACK_MAP_TOP_SPLIT, CANVAS_WIDTH - 28, CANVAS_HEIGHT - 46)
        _, split_media_rect = _active_moment_layout(split_map_rect)
        media_panel_size = (
            max(120, int(split_media_rect[2] - split_media_rect[0])),
            max(120, int(split_media_rect[3] - split_media_rect[1])),
        )

        media_cache = _build_moment_media_cache(
            moments,
            panel_size=media_panel_size,
            temp_dir=frame_dir,
            fps=fps,
            video_clip_seconds=moment_video_clip_seconds,
        )
        avatar_cache = _build_avatar_cache(moments=moments, avatar_size=92)
        moment_markers = _build_moment_markers(moments)
        for moment in moments:
            moment["playback_sec"] = _map_source_sec_to_playback_sec(
                source_sec=_safe_seconds(moment.get("sec")),
                source_point_secs=source_point_secs,
                playback_point_secs=playback_point_secs,
            )

        pause_timeline = _build_playback_pause_timeline(
            base_duration=movement_duration,
            moments=moments,
            media_cache=media_cache,
            photo_hold_seconds=photo_hold_seconds,
            text_hold_seconds=text_hold_seconds,
        )
        output_duration = max(movement_duration, _safe_seconds(pause_timeline.get("output_duration")))
        output_duration = min(output_duration, float(max_seconds))
        frame_count = int(max(2, math.ceil(output_duration * fps)))
        if frame_count > max_frames:
            frame_count = max_frames
            output_duration = frame_count / float(fps)

        if progress_callback:
            progress_callback(18, "Rendering playback frames")

        intervals = pause_timeline.get("intervals") or []
        interval_idx = 0
        for idx in range(frame_count):
            display_sec = min(output_duration, idx / float(fps))
            while interval_idx < len(intervals) - 1 and display_sec > _safe_seconds(intervals[interval_idx].get("output_end")):
                interval_idx += 1
            active_interval = intervals[interval_idx] if intervals else None
            motion_sec, active_moment, active_moment_offset = _resolve_output_state(active_interval, display_sec)
            playback_segment = _segment_for_playback_sec(playback_segments, motion_sec)
            frame = _render_frame(
                motion_sec=motion_sec,
                display_sec=display_sec,
                playback_duration=output_duration,
                points=points,
                point_secs=playback_point_secs,
                bounds=bounds,
                map_context_default=map_context_default,
                map_context_split=map_context_split,
                moment_markers=moment_markers,
                playback_segment=playback_segment,
                active_moment=active_moment,
                media_cache=media_cache,
                avatar_cache=avatar_cache,
                font=draw_font,
                small_font=small_font,
                tiny_font=tiny_font,
                watermark_font=watermark_font,
                active_moment_offset=active_moment_offset,
                fps=fps,
            )
            frame.save(
                os.path.join(frame_dir, f"frame_{idx + 1:06d}.jpg"),
                "JPEG",
                quality=92,
                optimize=True,
            )
            if progress_callback and (idx % 20 == 0 or idx == frame_count - 1):
                progress = 18 + int(((idx + 1) / float(frame_count)) * 66)
                progress_callback(progress, "Rendering playback frames")

        if progress_callback:
            progress_callback(90, "Encoding playback video")

        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            os.path.join(frame_dir, "frame_%06d.jpg"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    if progress_callback:
        progress_callback(98, "Playback video ready")

    return {
        "output_path": output_path,
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": round(output_duration, 2),
        "source_duration_seconds": round(source_duration, 2),
        "starts_at": (base_ts or trail.start_time or trail.created_at),
        "ends_at": (base_ts or trail.start_time or trail.created_at) + timedelta(seconds=source_duration),
    }
