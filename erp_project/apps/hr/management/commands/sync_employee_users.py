"""Backfill ERP users for HR employees without a linked login."""

from django.core.management.base import BaseCommand

from apps.hr.user_provisioning import sync_pending_employees_to_users


class Command(BaseCommand):
    help = 'Create Settings → Users logins for active HR employees without a linked user.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=500,
            help='Maximum employees to process (default 500).',
        )

    def handle(self, *args, **options):
        n = sync_pending_employees_to_users(limit=options['limit'])
        self.stdout.write(self.style.SUCCESS(f'Created {n} user(s).'))
