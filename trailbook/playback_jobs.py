import os
import threading
import time

from django.conf import settings
from django.core.files import File
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import TrailPlaybackShareRequest
from .playback_video import render_playback_share_request_video


_ACTIVE_JOB_IDS = set()
_ACTIVE_JOB_LOCK = threading.Lock()


def _progress_update(job_id, percent=None, note=None):
    updates = {"updated_at": timezone.now()}
    if percent is not None:
        safe_percent = max(0, min(100, int(percent)))
        updates["progress_percent"] = safe_percent
    if note is not None:
        updates["status_note"] = str(note)[:255]
    TrailPlaybackShareRequest.objects.filter(id=job_id).update(**updates)


def process_playback_share_request(job_id):
    with transaction.atomic():
        job = (
            TrailPlaybackShareRequest.objects.select_for_update()
            .select_related("trail", "requested_by")
            .filter(id=job_id)
            .first()
        )
        if not job:
            return False
        if job.status != TrailPlaybackShareRequest.STATUS_PENDING:
            return False
        job.status = TrailPlaybackShareRequest.STATUS_PROCESSING
        job.progress_percent = 2
        job.started_at = timezone.now()
        job.finished_at = None
        job.error_message = None
        job.status_note = "Preparing playback video render."
        job.save(
            update_fields=[
                "status",
                "progress_percent",
                "started_at",
                "finished_at",
                "error_message",
                "status_note",
                "updated_at",
            ]
        )

    def progress_cb(percent, note=None):
        _progress_update(job_id, percent=percent, note=note)

    render_output = None
    try:
        render_output = render_playback_share_request_video(
            playback_request_id=job_id,
            progress_callback=progress_cb,
        )
        output_path = render_output["output_path"]

        with transaction.atomic():
            ready_job = (
                TrailPlaybackShareRequest.objects.select_for_update()
                .select_related("trail")
                .get(id=job_id)
            )
            filename = (
                f"trail_{ready_job.trail_id}_playback_share_{ready_job.id}_"
                f"{int(time.time())}.mp4"
            )
            with open(output_path, "rb") as handle:
                ready_job.output_video.save(filename, File(handle), save=False)
            ready_job.status = TrailPlaybackShareRequest.STATUS_READY
            ready_job.progress_percent = 100
            ready_job.finished_at = timezone.now()
            ready_job.error_message = None
            ready_job.status_note = (
                f"Playback video ready ({render_output['duration_seconds']}s rendered)."
            )
            ready_job.save(
                update_fields=[
                    "output_video",
                    "status",
                    "progress_percent",
                    "finished_at",
                    "error_message",
                    "status_note",
                    "updated_at",
                ]
            )
        return True
    except Exception as exc:
        message = str(exc)[:2000]
        TrailPlaybackShareRequest.objects.filter(id=job_id).update(
            status=TrailPlaybackShareRequest.STATUS_FAILED,
            progress_percent=0,
            finished_at=timezone.now(),
            error_message=message,
            status_note="Playback video render failed.",
            updated_at=timezone.now(),
        )
        return False
    finally:
        if render_output and render_output.get("output_path"):
            try:
                os.remove(render_output["output_path"])
            except OSError:
                pass


def process_pending_playback_share_requests(limit=10):
    pending_ids = list(
        TrailPlaybackShareRequest.objects.filter(
            status=TrailPlaybackShareRequest.STATUS_PENDING,
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )
    processed = 0
    for job_id in pending_ids:
        if process_playback_share_request(job_id):
            processed += 1
    return processed


def _thread_run(job_id):
    close_old_connections()
    try:
        process_playback_share_request(job_id)
    finally:
        close_old_connections()
        with _ACTIVE_JOB_LOCK:
            _ACTIVE_JOB_IDS.discard(job_id)


def enqueue_playback_share_render(job_id):
    if not getattr(settings, "TRAILBOOK_PLAYBACK_AUTORUN", True):
        return False

    with _ACTIVE_JOB_LOCK:
        if job_id in _ACTIVE_JOB_IDS:
            return False
        _ACTIVE_JOB_IDS.add(job_id)

    worker = threading.Thread(
        target=_thread_run,
        args=(job_id,),
        name=f"trailbook-playback-{job_id}",
        daemon=True,
    )
    worker.start()
    return True
