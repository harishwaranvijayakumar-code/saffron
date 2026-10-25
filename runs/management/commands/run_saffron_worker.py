import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from runs.worker import process_next_invocation


class Command(BaseCommand):
    help = "Poll and execute eligible Saffron simulator invocations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one polling iteration and exit.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=2.0,
            help="Delay in seconds after an idle polling iteration.",
        )
        parser.add_argument(
            "--worker-id",
            type=uuid.UUID,
            default=None,
            help="Optional worker UUID.",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=0,
            help="Maximum processed invocations; zero means unlimited.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        max_jobs = options["max_jobs"]

        if not 0.2 <= interval <= 60:
            raise CommandError("--interval must be between 0.2 and 60.")

        if max_jobs < 0:
            raise CommandError("--max-jobs cannot be negative.")

        worker_id = options["worker_id"] or uuid.uuid4()
        processed = 0

        self.stdout.write(f"Worker ID: {worker_id}")

        try:
            while True:
                result = process_next_invocation(worker_id=worker_id)
                self.stdout.write(str(result))

                if result.get("status") != "IDLE" and "invocation_id" in result:
                    processed += 1

                if options["once"]:
                    break

                if max_jobs and processed >= max_jobs:
                    break

                if result.get("status") == "IDLE":
                    time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write("Worker interrupted; exiting.")
