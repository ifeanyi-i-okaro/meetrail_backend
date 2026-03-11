import time

from django.core.management.base import BaseCommand

from trailbook.playback_jobs import process_pending_playback_share_requests


class Command(BaseCommand):
    help = "Process queued TrailBook playback share render jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Maximum number of pending jobs to process per pass.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep processing continuously with short sleep intervals.",
        )
        parser.add_argument(
            "--sleep",
            type=int,
            default=5,
            help="Sleep seconds between loop iterations (only with --loop).",
        )

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        loop = bool(options["loop"])
        sleep_seconds = max(1, int(options["sleep"]))

        if not loop:
            processed = process_pending_playback_share_requests(limit=limit)
            self.stdout.write(self.style.SUCCESS(f"Processed {processed} playback job(s)."))
            return

        self.stdout.write(self.style.WARNING("Starting playback render worker loop..."))
        while True:
            processed = process_pending_playback_share_requests(limit=limit)
            if processed:
                self.stdout.write(self.style.SUCCESS(f"Processed {processed} playback job(s)."))
            time.sleep(sleep_seconds)
