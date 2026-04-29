"""Seed public holidays for 2026 (UAE/KSA). Islamic dates follow typical Gregorian projections — verify moon sightings."""

from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.models import Holiday


def _seed(rows):
    n_created = 0
    for d, name, location in rows:
        _, created = Holiday.objects.get_or_create(
            date=d,
            name=name,
            location=location,
            defaults={'is_recurring': False, 'is_active': True},
        )
        if created:
            n_created += 1
    return n_created


class Command(BaseCommand):
    help = 'Insert UAE/KSA holiday calendar rows (defaults to year 2026 projections).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            default=2026,
            help='Calendar year to seed (default: 2026)',
        )

    def handle(self, *args, **options):
        y = int(options['year'])
        # Shared observances (typical projections — confirm annually).
        both = [
            (date(y, 1, 1), "New Year's Day", 'both'),
            (date(y, 3, 20), 'Eid al-Fitr (1)', 'both'),
            (date(y, 3, 21), 'Eid al-Fitr (2)', 'both'),
            (date(y, 3, 22), 'Eid al-Fitr (3)', 'both'),
            (date(y, 5, 26), 'Arafat Day', 'both'),
            (date(y, 5, 27), 'Eid al-Adha (1)', 'both'),
            (date(y, 5, 28), 'Eid al-Adha (2)', 'both'),
            (date(y, 5, 29), 'Eid al-Adha (3)', 'both'),
            (date(y, 6, 16), 'Islamic New Year', 'both'),
            (date(y, 8, 25), "Prophet's Birthday (PBUH)", 'both'),
        ]
        uae_only = [
            (date(y, 12, 2), 'UAE National Day', 'uae'),
            (date(y, 12, 3), 'UAE National Day (2)', 'uae'),
        ]
        ksa_only = [
            (date(y, 2, 22), 'Saudi Founding Day', 'ksa'),
            (date(y, 9, 23), 'Saudi National Day', 'ksa'),
        ]
        all_rows = both + uae_only + ksa_only
        created = _seed(all_rows)
        self.stdout.write(
            self.style.SUCCESS(f'Holidays processed for {y}: {created} new rows ({len(all_rows)} definitions checked).')
        )
