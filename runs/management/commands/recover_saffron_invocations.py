from django.core.management.base import BaseCommand, CommandError

from runs.recovery import recover_expired_invocations


class Command(BaseCommand):
    help = "Recover Saffron invocations with expired execution leases."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum invocations to recover in one pass.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000.")

        recovered = recover_expired_invocations(limit=limit)

        self.stdout.write(
            f"Marked {len(recovered)} invocation(s) as OUTCOME_UNKNOWN."
        )

        for invocation_id in recovered:
            self.stdout.write(invocation_id)
