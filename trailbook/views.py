import math
from datetime import datetime, time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ChatThread, Notification, Profile
from accounts.utils import send_push_notification

from .models import (
    TrailEntry,
    TrailPoint,
    TrailMoment,
    TrailMomentComment,
    TrailMomentLike,
    TrailShare,
    TrailPlaybackShareRequest,
)
from .playback_jobs import enqueue_playback_share_render
from .serializers import (
    TrailEntryStartSerializer,
    TrailEntryStopSerializer,
    TrailEntryUpdateSerializer,
    TrailPointBulkSerializer,
    TrailMomentCreateSerializer,
    TrailMomentCommentCreateSerializer,
    TrailShareCreateSerializer,
    TrailShareRevokeSerializer,
    TrailPlaybackShareRequestSerializer,
    TrailEntryListSerializer,
    TrailEntryDetailSerializer,
    TrailEntryMomentsOnlyDetailSerializer,
    TrailEntryMomentsMapSerializer,
    TrailReplaySerializer,
    TrailMomentSerializer,
    TrailMomentCommentSerializer,
    TrailPlaybackShareRequestStatusSerializer,
)

User = get_user_model()


def _haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _compute_distance_m(point_pairs):
    if len(point_pairs) < 2:
        return 0.0
    distance = 0.0
    prev_lat, prev_lng = point_pairs[0]
    for lat, lng in point_pairs[1:]:
        distance += _haversine_m(prev_lat, prev_lng, lat, lng)
        prev_lat, prev_lng = lat, lng
    return distance


def _build_line_geometry(point_pairs):
    if not point_pairs:
        return None
    coordinates = [[lng, lat] for lat, lng in point_pairs]
    return {"type": "LineString", "coordinates": coordinates}


def _extract_line_coordinates(geometry):
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") != "LineString":
        return []
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return []
    sanitized = []
    for item in coordinates:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lng = item[0]
        lat = item[1]
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            sanitized.append([float(lng), float(lat)])
    return sanitized


def _can_view_trail(user, trail):
    can_view, _ = _resolve_trail_access(user, trail)
    return can_view


def _can_view_full_trail(user, trail):
    _, can_view_full = _resolve_trail_access(user, trail)
    return can_view_full


def _resolve_trail_access(user, trail):
    if user.id == trail.user_id:
        return True, True

    inherited_can_view = False
    inherited_can_view_full = False
    if trail.visibility == TrailEntry.VISIBILITY_PUBLIC:
        inherited_can_view = True
        inherited_can_view_full = trail.share_scope == TrailEntry.SHARE_SCOPE_FULL
    elif trail.visibility == TrailEntry.VISIBILITY_FOLLOWERS:
        try:
            follows_owner = trail.user.profile.followers.filter(user_id=user.id).exists()
        except Exception:
            follows_owner = False
        if follows_owner:
            inherited_can_view = True
            inherited_can_view_full = trail.share_scope == TrailEntry.SHARE_SCOPE_FULL

    direct_user_scopes = list(
        TrailShare.objects.filter(trail_id=trail.id, target_user_id=user.id).values_list(
            "share_scope",
            flat=True,
        )
    )
    group_scopes = list(
        TrailShare.objects.filter(trail_id=trail.id, target_group__participants=user)
        .values_list("share_scope", flat=True)
    )
    shared_scopes = direct_user_scopes + group_scopes
    shared_can_view = bool(shared_scopes)
    shared_can_view_full = TrailEntry.SHARE_SCOPE_FULL in shared_scopes

    can_view = inherited_can_view or shared_can_view
    can_view_full = inherited_can_view_full or shared_can_view_full
    return can_view, can_view_full


def _compute_follower_owner_ids(user):
    try:
        return list(
            Profile.objects.filter(followers=user.profile).values_list("user_id", flat=True)
        )
    except Exception:
        return []


def _compute_shared_trail_ids_for_user(user):
    group_ids = list(
        ChatThread.objects.filter(is_group=True, participants=user).values_list("id", flat=True)
    )
    shared_trail_ids = set(
        TrailShare.objects.filter(target_user=user).values_list("trail_id", flat=True)
    )
    if group_ids:
        shared_trail_ids.update(
            TrailShare.objects.filter(target_group_id__in=group_ids).values_list("trail_id", flat=True)
        )
    return shared_trail_ids


def _allowed_follower_user_ids(user):
    try:
        return set(
            user.profile.followers.values_list("user_id", flat=True)
        )
    except Exception:
        return set()


def _allowed_group_ids(user):
    return set(
        ChatThread.objects.filter(is_group=True, participants=user)
        .values_list("id", flat=True)
    )


def _actor_notification_meta(actor, request=None):
    actor_profile = getattr(actor, "profile", None)
    actor_name = (
        actor_profile.name
        if actor_profile and getattr(actor_profile, "name", "")
        else getattr(actor, "username", "User")
    )
    actor_profile_id = actor_profile.id if actor_profile else None
    actor_avatar = None
    if (
        request
        and actor_profile
        and getattr(actor_profile, "profile_picture", None)
    ):
        try:
            actor_avatar = request.build_absolute_uri(actor_profile.profile_picture.url)
        except Exception:
            actor_avatar = None
    return actor_name, actor_profile_id, actor_avatar


def _notify_user(
    *,
    recipient,
    actor,
    notification_type,
    message,
    request=None,
    extra_data=None,
):
    if not recipient or not actor or recipient.id == actor.id:
        return None
    actor_name, actor_profile_id, actor_avatar = _actor_notification_meta(
        actor,
        request=request,
    )
    notification = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        type=notification_type,
        message=message,
    )
    payload = {
        "id": notification.id,
        "type": notification_type,
        "message": message,
        "actor_name": actor_name,
        "actor_profile_id": actor_profile_id,
        "actor_avatar": actor_avatar,
        "created_at": notification.created_at.isoformat(),
    }
    if isinstance(extra_data, dict):
        payload.update(extra_data)

    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{recipient.id}",
                {"type": "notify", "data": payload},
            )
    except Exception:
        pass

    try:
        tokens = list(recipient.push_tokens.values_list("token", flat=True))
        if tokens:
            push_data = {
                "type": notification_type,
                "actor_name": actor_name,
            }
            if actor_profile_id is not None:
                push_data["actor_profile_id"] = str(actor_profile_id)
            if actor_avatar:
                push_data["actor_avatar"] = actor_avatar
            if isinstance(extra_data, dict):
                for key, value in extra_data.items():
                    if value is None:
                        continue
                    push_data[str(key)] = str(value)
            send_push_notification(
                tokens=tokens,
                title=actor_name,
                body=message,
                data=push_data,
                image=actor_avatar,
            )
    except Exception:
        pass

    return notification


def _can_view_playback_request(user, playback_request):
    if user.id == playback_request.requested_by_id:
        return True
    if user.id == playback_request.trail.user_id:
        return True
    if user.id in (playback_request.user_ids or []):
        return True
    group_ids = set(playback_request.group_ids or [])
    if not group_ids:
        return False
    return ChatThread.objects.filter(
        id__in=group_ids,
        participants=user,
    ).exists()


def _liked_moment_ids_for_user(user, moment_ids):
    if not user or not user.is_authenticated:
        return set()
    ids = [int(item) for item in (moment_ids or []) if item]
    if not ids:
        return set()
    return set(
        TrailMomentLike.objects.filter(
            user_id=user.id,
            moment_id__in=ids,
        ).values_list("moment_id", flat=True)
    )


def _trail_serializer_context(request, trail=None):
    context = {"request": request}
    if trail is None:
        return context
    try:
        moment_ids = [moment.id for moment in trail.moments.all()]
    except Exception:
        moment_ids = list(
            TrailMoment.objects.filter(trail_id=trail.id).values_list("id", flat=True)
        )
    context["liked_moment_ids"] = _liked_moment_ids_for_user(request.user, moment_ids)
    return context


class TrailBookStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        active = TrailEntry.objects.filter(
            user=request.user,
            status=TrailEntry.STATUS_RECORDING,
        ).order_by("-id").first()
        if active:
            return Response(
                {
                    "error": "You already have an active trail.",
                    "active_trail_id": active.id,
                },
                status=400,
            )

        serializer = TrailEntryStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        trail = TrailEntry.objects.create(
            user=request.user,
            title=payload.get("title", ""),
            start_lat=payload.get("start_lat"),
            start_lng=payload.get("start_lng"),
            visibility=TrailEntry.VISIBILITY_PRIVATE,
            status=TrailEntry.STATUS_RECORDING,
        )

        follower_ids = _allowed_follower_user_ids(request.user)
        if follower_ids:
            recipients = User.objects.filter(id__in=follower_ids).exclude(id=request.user.id)
            trail_label = trail.title.strip() if trail.title.strip() else f"Trail #{trail.id}"
            for recipient in recipients:
                _notify_user(
                    recipient=recipient,
                    actor=request.user,
                    notification_type="trail_start",
                    message=f"started a new trail: {trail_label}",
                    request=request,
                    extra_data={"trail_id": trail.id},
                )

        out = TrailEntryDetailSerializer(
            trail,
            context=_trail_serializer_context(request, trail),
        )
        return Response(out.data, status=201)


class TrailBookPointBulkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
            status=TrailEntry.STATUS_RECORDING,
        )

        serializer = TrailPointBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        points_data = serializer.validated_data["points"]

        point_objs = []
        for item in points_data:
            point_objs.append(
                TrailPoint(
                    trail=trail,
                    lat=item["lat"],
                    lng=item["lng"],
                    recorded_at=item.get("recorded_at") or timezone.now(),
                    accuracy=item.get("accuracy"),
                    speed=item.get("speed"),
                    mno=item.get("mno"),
                    mcc_mnc=item.get("mcc_mnc"),
                    network_type=item.get("network_type"),
                    rsrp=item.get("rsrp"),
                    rsrq=item.get("rsrq"),
                    sinr=item.get("sinr"),
                    rssi_dbm=item.get("rssi_dbm"),
                    cell_id=item.get("cell_id"),
                    tac=item.get("tac"),
                    signal_sampled_at=item.get("signal_sampled_at"),
                )
            )
        TrailPoint.objects.bulk_create(point_objs)

        if point_objs:
            first_point = point_objs[0]
            last_point = point_objs[-1]
            if trail.start_lat is None:
                trail.start_lat = first_point.lat
            if trail.start_lng is None:
                trail.start_lng = first_point.lng
            trail.end_lat = last_point.lat
            trail.end_lng = last_point.lng
            coordinates = _extract_line_coordinates(trail.path_geometry)
            for point in point_objs:
                coordinates.append([point.lng, point.lat])
            trail.path_geometry = {"type": "LineString", "coordinates": coordinates}
            trail.save(
                update_fields=[
                    "start_lat",
                    "start_lng",
                    "end_lat",
                    "end_lng",
                    "path_geometry",
                    "updated_at",
                ]
            )

        return Response({"success": True, "created": len(point_objs)}, status=201)


class TrailBookMomentCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
            status=TrailEntry.STATUS_RECORDING,
        )

        payload = {
            "moment_type": request.data.get("moment_type"),
            "caption": request.data.get("caption"),
            "text": request.data.get("text"),
            "media_file": request.FILES.get("media_file"),
            "lat": request.data.get("lat"),
            "lng": request.data.get("lng"),
            "recorded_at": request.data.get("recorded_at"),
        }
        serializer = TrailMomentCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        moment = TrailMoment.objects.create(
            trail=trail,
            moment_type=data["moment_type"],
            caption=data.get("caption"),
            text=data.get("text"),
            media_file=data.get("media_file"),
            lat=data.get("lat"),
            lng=data.get("lng"),
            recorded_at=data.get("recorded_at") or timezone.now(),
        )

        if moment.lat is not None and trail.end_lat is None:
            trail.end_lat = moment.lat
            trail.end_lng = moment.lng
            trail.save(update_fields=["end_lat", "end_lng", "updated_at"])

        out = TrailMomentSerializer(
            moment,
            context={
                "request": request,
                "liked_moment_ids": set(),
            },
        )
        return Response(out.data, status=201)


class TrailBookMomentCommentsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_moment_for_viewer(self, user, moment_id):
        moment = get_object_or_404(
            TrailMoment.objects.select_related("trail", "trail__user"),
            id=moment_id,
        )
        can_view, _ = _resolve_trail_access(user, moment.trail)
        if not can_view:
            return None
        return moment

    def get(self, request, moment_id):
        moment = self._get_moment_for_viewer(request.user, moment_id)
        if moment is None:
            return Response({"error": "Not allowed"}, status=403)

        comments_qs = (
            TrailMomentComment.objects.filter(moment_id=moment.id)
            .select_related("user", "user__profile")
            .order_by("created_at", "id")
        )
        flat_rows = TrailMomentCommentSerializer(
            comments_qs,
            many=True,
            context={"request": request},
        ).data

        by_id = {}
        roots = []
        for row in flat_rows:
            row["replies"] = []
            by_id[row["id"]] = row

        for row in flat_rows:
            parent_id = row.get("parent")
            if parent_id and parent_id in by_id:
                by_id[parent_id]["replies"].append(row)
            else:
                roots.append(row)

        return Response({"results": roots, "count": len(flat_rows)}, status=200)

    def post(self, request, moment_id):
        moment = self._get_moment_for_viewer(request.user, moment_id)
        if moment is None:
            return Response({"error": "Not allowed"}, status=403)

        payload = {}
        parent_id = request.data.get("parent_id")
        if parent_id not in (None, "", "null", "None"):
            payload["parent_id"] = parent_id
        if "text" in request.data:
            payload["text"] = request.data.get("text")
        media_file = request.FILES.get("media_file")
        if media_file is not None:
            payload["media_file"] = media_file
        serializer = TrailMomentCommentCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        parent = None
        parent_id = data.get("parent_id")
        if parent_id:
            parent = get_object_or_404(
                TrailMomentComment,
                id=parent_id,
                moment_id=moment.id,
            )

        comment = TrailMomentComment.objects.create(
            moment=moment,
            user=request.user,
            parent=parent,
            text=data.get("text"),
            media_file=data.get("media_file"),
        )

        trail_label = (
            moment.trail.title.strip()
            if (moment.trail.title or "").strip()
            else f"Trail #{moment.trail_id}"
        )
        if moment.trail.user_id != request.user.id:
            _notify_user(
                recipient=moment.trail.user,
                actor=request.user,
                notification_type="trail_comment",
                message=f"commented on your moment in {trail_label}",
                request=request,
                extra_data={
                    "trail_id": moment.trail_id,
                    "moment_id": moment.id,
                    "comment_id": comment.id,
                },
            )

        if parent and parent.user_id not in {request.user.id, moment.trail.user_id}:
            _notify_user(
                recipient=parent.user,
                actor=request.user,
                notification_type="trail_reply",
                message=f"replied to your comment in {trail_label}",
                request=request,
                extra_data={
                    "trail_id": moment.trail_id,
                    "moment_id": moment.id,
                    "comment_id": comment.id,
                    "parent_comment_id": parent.id,
                },
            )

        out = TrailMomentCommentSerializer(comment, context={"request": request}).data
        out["replies"] = []
        return Response(out, status=201)


class TrailBookMomentLikeView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_moment_for_viewer(self, user, moment_id):
        moment = get_object_or_404(
            TrailMoment.objects.select_related("trail", "trail__user"),
            id=moment_id,
        )
        can_view, _ = _resolve_trail_access(user, moment.trail)
        if not can_view:
            return None
        return moment

    def post(self, request, moment_id):
        moment = self._get_moment_for_viewer(request.user, moment_id)
        if moment is None:
            return Response({"error": "Not allowed"}, status=403)

        like, created = TrailMomentLike.objects.get_or_create(
            moment_id=moment.id,
            user_id=request.user.id,
        )
        likes_count = TrailMomentLike.objects.filter(moment_id=moment.id).count()

        if created and moment.trail.user_id != request.user.id:
            trail_label = (
                moment.trail.title.strip()
                if (moment.trail.title or "").strip()
                else f"Trail #{moment.trail_id}"
            )
            _notify_user(
                recipient=moment.trail.user,
                actor=request.user,
                notification_type="like",
                message=f"liked your moment in {trail_label}",
                request=request,
                extra_data={
                    "trail_id": moment.trail_id,
                    "moment_id": moment.id,
                    "like_id": like.id,
                },
            )

        return Response(
            {
                "success": True,
                "liked": True,
                "moment_id": moment.id,
                "likes_count": likes_count,
            },
            status=200,
        )

    def delete(self, request, moment_id):
        moment = self._get_moment_for_viewer(request.user, moment_id)
        if moment is None:
            return Response({"error": "Not allowed"}, status=403)
        TrailMomentLike.objects.filter(
            moment_id=moment.id,
            user_id=request.user.id,
        ).delete()
        likes_count = TrailMomentLike.objects.filter(moment_id=moment.id).count()
        return Response(
            {
                "success": True,
                "liked": False,
                "moment_id": moment.id,
                "likes_count": likes_count,
            },
            status=200,
        )


class TrailBookStopView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
            status=TrailEntry.STATUS_RECORDING,
        )

        serializer = TrailEntryStopSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "title" in data:
            trail.title = data["title"]
        if "final_comment" in data:
            trail.final_comment = data["final_comment"]
        if "visibility" in data:
            trail.visibility = data["visibility"]
        requested_scope = data.get("share_scope", trail.share_scope)
        if trail.visibility == TrailEntry.VISIBILITY_PRIVATE:
            trail.share_scope = TrailEntry.SHARE_SCOPE_FULL
        else:
            trail.share_scope = requested_scope
        if "end_lat" in data:
            trail.end_lat = data["end_lat"]
        if "end_lng" in data:
            trail.end_lng = data["end_lng"]

        points = list(
            trail.points.order_by("recorded_at", "id").values_list("lat", "lng")
        )
        if points:
            if trail.start_lat is None:
                trail.start_lat = points[0][0]
            if trail.start_lng is None:
                trail.start_lng = points[0][1]
            if trail.end_lat is None:
                trail.end_lat = points[-1][0]
            if trail.end_lng is None:
                trail.end_lng = points[-1][1]
            trail.distance_m = _compute_distance_m(points)
            trail.path_geometry = _build_line_geometry(points)

        trail.status = TrailEntry.STATUS_COMPLETED
        trail.end_time = timezone.now()
        trail.save()

        out = TrailEntryDetailSerializer(
            trail,
            context=_trail_serializer_context(request, trail),
        )
        return Response(out.data, status=200)


class TrailBookShareOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        followers_payload = []
        try:
            follower_profiles = request.user.profile.followers.select_related("user")
        except Exception:
            follower_profiles = []

        for profile in follower_profiles:
            followers_payload.append(
                {
                    "id": profile.user_id,
                    "username": getattr(profile.user, "username", ""),
                    "name": profile.name or getattr(profile.user, "username", ""),
                }
            )

        groups_qs = (
            ChatThread.objects.filter(is_group=True, participants=request.user)
            .distinct()
            .annotate(member_count=Count("participants", distinct=True))
        )
        groups_payload = [
            {
                "id": item.id,
                "name": item.name or f"Group {item.id}",
                "member_count": item.member_count,
            }
            for item in groups_qs
        ]

        return Response(
            {
                "followers": followers_payload,
                "groups": groups_payload,
            },
            status=200,
        )


class TrailBookShareView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
        )
        serializer = TrailShareCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        user_ids = payload.get("user_ids", []) or []
        group_ids = payload.get("group_ids", []) or []
        share_scope = payload.get("share_scope", TrailEntry.SHARE_SCOPE_FULL)
        share_public = bool(payload.get("share_public"))

        allowed_users = _allowed_follower_user_ids(request.user)
        blocked_user_ids = [item for item in user_ids if item not in allowed_users]
        if blocked_user_ids:
            return Response(
                {
                    "error": "You can only share with users who follow you.",
                    "blocked_user_ids": blocked_user_ids,
                },
                status=400,
            )

        allowed_groups = _allowed_group_ids(request.user)
        blocked_group_ids = [item for item in group_ids if item not in allowed_groups]
        if blocked_group_ids:
            return Response(
                {
                    "error": "You can only share with groups you belong to.",
                    "blocked_group_ids": blocked_group_ids,
                },
                status=400,
            )

        created = 0
        updated = 0
        public_updated = False
        notify_user_ids = set()

        if share_public:
            update_fields = []
            if trail.visibility != TrailEntry.VISIBILITY_PUBLIC:
                trail.visibility = TrailEntry.VISIBILITY_PUBLIC
                update_fields.append("visibility")
            if trail.share_scope != share_scope:
                trail.share_scope = share_scope
                update_fields.append("share_scope")
            if update_fields:
                trail.save(update_fields=update_fields)
                public_updated = True

        for user_id in user_ids:
            share, was_created = TrailShare.objects.get_or_create(
                trail=trail,
                target_user_id=user_id,
                defaults={
                    "shared_by": request.user,
                    "share_scope": share_scope,
                },
            )
            if was_created:
                created += 1
                notify_user_ids.add(user_id)
                continue
            changed = False
            if share.shared_by_id != request.user.id:
                share.shared_by = request.user
                changed = True
            if share.share_scope != share_scope:
                share.share_scope = share_scope
                changed = True
            if changed:
                share.save(update_fields=["shared_by", "share_scope"])
                updated += 1
                notify_user_ids.add(user_id)

        for group_id in group_ids:
            share, was_created = TrailShare.objects.get_or_create(
                trail=trail,
                target_group_id=group_id,
                defaults={
                    "shared_by": request.user,
                    "share_scope": share_scope,
                },
            )
            if was_created:
                created += 1
                group_member_ids = list(
                    ChatThread.objects.filter(id=group_id)
                    .values_list("participants__id", flat=True)
                )
                notify_user_ids.update(
                    uid for uid in group_member_ids if uid and uid != request.user.id
                )
                continue
            changed = False
            if share.shared_by_id != request.user.id:
                share.shared_by = request.user
                changed = True
            if share.share_scope != share_scope:
                share.share_scope = share_scope
                changed = True
            if changed:
                share.save(update_fields=["shared_by", "share_scope"])
                updated += 1
                group_member_ids = list(
                    ChatThread.objects.filter(id=group_id)
                    .values_list("participants__id", flat=True)
                )
                notify_user_ids.update(
                    uid for uid in group_member_ids if uid and uid != request.user.id
                )

        if notify_user_ids:
            recipients = User.objects.filter(id__in=notify_user_ids).exclude(id=request.user.id)
            trail_label = trail.title.strip() if (trail.title or "").strip() else f"Trail #{trail.id}"
            for recipient in recipients:
                _notify_user(
                    recipient=recipient,
                    actor=request.user,
                    notification_type="trail_share",
                    message=f"shared a trail with you: {trail_label}",
                    request=request,
                    extra_data={
                        "trail_id": trail.id,
                        "share_scope": share_scope,
                    },
                )

        return Response(
            {
                "success": True,
                "created": created,
                "updated": updated,
                "public_updated": public_updated,
                "share_public": share_public,
                "share_scope": share_scope,
            },
            status=200,
        )


class TrailBookShareStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
        )
        shares_qs = (
            TrailShare.objects.filter(trail_id=trail.id)
            .select_related("target_user", "target_user__profile", "target_group")
            .order_by("-created_at")
        )
        users_payload = []
        groups_payload = []
        for share in shares_qs:
            if share.target_user_id:
                profile = getattr(share.target_user, "profile", None)
                users_payload.append(
                    {
                        "id": share.target_user_id,
                        "username": getattr(share.target_user, "username", ""),
                        "name": (
                            profile.name
                            if profile and getattr(profile, "name", "")
                            else getattr(share.target_user, "username", "")
                        ),
                        "share_scope": share.share_scope,
                    }
                )
            elif share.target_group_id:
                groups_payload.append(
                    {
                        "id": share.target_group_id,
                        "name": (
                            share.target_group.name
                            if share.target_group and share.target_group.name
                            else f"Group {share.target_group_id}"
                        ),
                        "share_scope": share.share_scope,
                    }
                )

        return Response(
            {
                "trail_id": trail.id,
                "visibility": trail.visibility,
                "share_scope": trail.share_scope,
                "is_public": trail.visibility == TrailEntry.VISIBILITY_PUBLIC,
                "users": users_payload,
                "groups": groups_payload,
            },
            status=200,
        )


class TrailBookShareRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
        )
        serializer = TrailShareRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_ids = data.get("user_ids", []) or []
        group_ids = data.get("group_ids", []) or []
        revoke_public = bool(data.get("revoke_public"))
        revoke_all = bool(data.get("revoke_all"))
        set_private = bool(data.get("set_private", True))

        shares_qs = TrailShare.objects.filter(trail_id=trail.id)
        removed_users = 0
        removed_groups = 0
        removed_total = 0

        if revoke_all:
            removed_users = shares_qs.filter(target_user__isnull=False).count()
            removed_groups = shares_qs.filter(target_group__isnull=False).count()
            removed_total, _ = shares_qs.delete()
        else:
            if user_ids:
                qs = shares_qs.filter(target_user_id__in=user_ids)
                removed_users = qs.count()
                deleted, _ = qs.delete()
                removed_total += deleted
            if group_ids:
                qs = shares_qs.filter(target_group_id__in=group_ids)
                removed_groups = qs.count()
                deleted, _ = qs.delete()
                removed_total += deleted

        visibility_changed = False
        if set_private and (revoke_all or revoke_public):
            update_fields = []
            if trail.visibility != TrailEntry.VISIBILITY_PRIVATE:
                trail.visibility = TrailEntry.VISIBILITY_PRIVATE
                update_fields.append("visibility")
            if trail.share_scope != TrailEntry.SHARE_SCOPE_FULL:
                trail.share_scope = TrailEntry.SHARE_SCOPE_FULL
                update_fields.append("share_scope")
            if update_fields:
                trail.save(update_fields=update_fields + ["updated_at"])
                visibility_changed = True

        return Response(
            {
                "success": True,
                "trail_id": trail.id,
                "removed_total": removed_total,
                "removed_users": removed_users,
                "removed_groups": removed_groups,
                "visibility": trail.visibility,
                "share_scope": trail.share_scope,
                "visibility_changed": visibility_changed,
            },
            status=200,
        )


class TrailBookPlaybackShareView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
        )
        serializer = TrailPlaybackShareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        user_ids = payload.get("user_ids", []) or []
        group_ids = payload.get("group_ids", []) or []

        allowed_users = _allowed_follower_user_ids(request.user)
        blocked_user_ids = [item for item in user_ids if item not in allowed_users]
        if blocked_user_ids:
            return Response(
                {
                    "error": "You can only share playback with users who follow you.",
                    "blocked_user_ids": blocked_user_ids,
                },
                status=400,
            )
        allowed_groups = _allowed_group_ids(request.user)
        blocked_group_ids = [item for item in group_ids if item not in allowed_groups]
        if blocked_group_ids:
            return Response(
                {
                    "error": "You can only share playback with groups you belong to.",
                    "blocked_group_ids": blocked_group_ids,
                },
                status=400,
            )

        job = TrailPlaybackShareRequest.objects.create(
            trail=trail,
            requested_by=request.user,
            user_ids=user_ids,
            group_ids=group_ids,
            status=TrailPlaybackShareRequest.STATUS_PENDING,
            progress_percent=0,
            status_note=(
                "Playback video rendering is queued. Final rendering pipeline "
                "will preserve timeline and flash moments."
            ),
        )

        if settings.TRAILBOOK_PLAYBACK_AUTORUN:
            enqueue_playback_share_render(job.id)

        return Response(
            {
                "success": True,
                "request_id": job.id,
                "status": job.status,
                "note": job.status_note,
                "progress_percent": job.progress_percent,
            },
            status=202,
        )


class TrailBookPlaybackShareRequestStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, request_id):
        playback_request = get_object_or_404(
            TrailPlaybackShareRequest.objects.select_related("trail", "requested_by"),
            id=request_id,
        )
        if not _can_view_playback_request(request.user, playback_request):
            return Response({"error": "Not allowed"}, status=403)
        serializer = TrailPlaybackShareRequestStatusSerializer(
            playback_request,
            context={"request": request},
        )
        return Response(serializer.data, status=200)


class TrailBookListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mine = str(request.query_params.get("mine", "")).lower() in {"1", "true", "yes"}
        scope = str(request.query_params.get("scope", "all")).strip().lower()
        moment_type = request.query_params.get("type")
        from_param = request.query_params.get("from")
        to_param = request.query_params.get("to")
        ordering = request.query_params.get("ordering", "-start_time")

        qs = TrailEntry.objects.select_related("user").annotate(
            moments_count=Count("moments", distinct=True),
            points_count=Count("points", distinct=True),
        )

        if mine:
            qs = qs.filter(user=request.user)
        else:
            follower_owner_ids = _compute_follower_owner_ids(request.user)
            shared_trail_ids = _compute_shared_trail_ids_for_user(request.user)
            shared_filter = Q(id__in=shared_trail_ids) if shared_trail_ids else Q(pk__in=[])

            if scope == "followers":
                if not follower_owner_ids:
                    qs = qs.none()
                else:
                    qs = qs.filter(
                        user_id__in=follower_owner_ids,
                    ).filter(
                        Q(visibility=TrailEntry.VISIBILITY_PUBLIC)
                        | Q(visibility=TrailEntry.VISIBILITY_FOLLOWERS),
                    )
            elif scope == "shared":
                if not shared_trail_ids:
                    qs = qs.none()
                else:
                    qs = qs.filter(shared_filter).exclude(user=request.user)
            elif scope == "public":
                qs = qs.filter(visibility=TrailEntry.VISIBILITY_PUBLIC).exclude(
                    user=request.user,
                )
            else:
                qs = qs.filter(
                    Q(user=request.user)
                    | Q(visibility=TrailEntry.VISIBILITY_PUBLIC)
                    | Q(
                        visibility=TrailEntry.VISIBILITY_FOLLOWERS,
                        user_id__in=follower_owner_ids,
                    )
                    | shared_filter
                )

        if moment_type in {choice[0] for choice in TrailMoment.TYPE_CHOICES}:
            qs = qs.filter(moments__moment_type=moment_type).distinct()

        if from_param:
            dt_from = parse_datetime(from_param)
            if dt_from is None:
                date_from = parse_date(from_param)
                if date_from:
                    dt_from = timezone.make_aware(datetime.combine(date_from, time.min))
            if dt_from is not None:
                qs = qs.filter(start_time__gte=dt_from)

        if to_param:
            dt_to = parse_datetime(to_param)
            if dt_to is None:
                date_to = parse_date(to_param)
                if date_to:
                    dt_to = timezone.make_aware(datetime.combine(date_to, time.max))
            if dt_to is not None:
                qs = qs.filter(start_time__lte=dt_to)

        allowed_ordering = {
            "start_time",
            "-start_time",
            "created_at",
            "-created_at",
            "distance_m",
            "-distance_m",
        }
        if ordering not in allowed_ordering:
            ordering = "-start_time"
        qs = qs.order_by(ordering).distinct()

        rows = list(qs)
        for trail in rows:
            _, can_view_full = _resolve_trail_access(request.user, trail)
            trail._viewer_can_view_full = can_view_full

        serializer = TrailEntryListSerializer(rows, many=True, context={"request": request})
        return Response({"results": serializer.data}, status=200)


class TrailBookDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trail_id):
        lite = str(request.query_params.get("lite", "")).lower() in {"1", "true", "yes"}
        prefetch = ("moments",) if lite else ("points", "moments")
        trail = get_object_or_404(
            TrailEntry.objects.prefetch_related(*prefetch),
            id=trail_id,
        )
        can_view, can_view_full = _resolve_trail_access(request.user, trail)
        if not can_view:
            return Response({"error": "Not allowed"}, status=403)
        trail._viewer_can_view_full = can_view_full
        if lite:
            serializer_class = TrailEntryMomentsMapSerializer
        elif can_view_full:
            serializer_class = TrailEntryDetailSerializer
        else:
            serializer_class = TrailEntryMomentsOnlyDetailSerializer
        serializer = serializer_class(
            trail,
            context=_trail_serializer_context(request, trail),
        )
        return Response(serializer.data, status=200)

    def patch(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry.objects.prefetch_related("points", "moments"),
            id=trail_id,
            user=request.user,
        )
        serializer = TrailEntryUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []
        if "title" in data:
            trail.title = data["title"]
            update_fields.append("title")
        if "final_comment" in data:
            trail.final_comment = data["final_comment"]
            update_fields.append("final_comment")
        if "visibility" in data:
            trail.visibility = data["visibility"]
            update_fields.append("visibility")
        if "share_scope" in data:
            trail.share_scope = data["share_scope"]
            if "share_scope" not in update_fields:
                update_fields.append("share_scope")
        if trail.visibility == TrailEntry.VISIBILITY_PRIVATE:
            if trail.share_scope != TrailEntry.SHARE_SCOPE_FULL:
                trail.share_scope = TrailEntry.SHARE_SCOPE_FULL
                if "share_scope" not in update_fields:
                    update_fields.append("share_scope")
        if update_fields:
            trail.save(update_fields=list(dict.fromkeys(update_fields + ["updated_at"])))

        trail._viewer_can_view_full = True
        out = TrailEntryDetailSerializer(
            trail,
            context=_trail_serializer_context(request, trail),
        )
        return Response(out.data, status=200)

    def delete(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry,
            id=trail_id,
            user=request.user,
        )
        trail.delete()
        return Response({"success": True}, status=200)


class TrailBookReplayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trail_id):
        trail = get_object_or_404(
            TrailEntry.objects.prefetch_related("points", "moments"),
            id=trail_id,
        )
        can_view, can_view_full = _resolve_trail_access(request.user, trail)
        if not can_view:
            return Response({"error": "Not allowed"}, status=403)
        trail._viewer_can_view_full = can_view_full
        if not can_view_full:
            return Response(
                {"error": "Playback is unavailable for moments-only shared trails."},
                status=403,
            )
        serializer = TrailReplaySerializer(
            trail,
            context=_trail_serializer_context(request, trail),
        )
        return Response(serializer.data, status=200)
