"""Seed public holidays — UAE and KSA as separate rows (no shared 'both' scope).

Full Islamic calendars are preset per Gregorian year below; for other years only fixed
national/Gregorian dates are inserted (re-run after you add a preset or enter Eid manually).
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.models import Holiday

# (month, day) tuples for Islamic-based public holidays — update when official calendars publish.
_ISLAMIC_PRESETS = {
    2026: {
        'fitr_start': (3, 20),
        'fitr_days': 3,
        'arafat': (5, 26),
        'adha_start': (5, 27),
        'adha_days': 3,
        'hijri_new_year': (6, 16),
        'mawlid': (8, 25),
    },
    2027: {
        'fitr_start': (3, 9),
        'fitr_days': 3,
        'arafat': (5, 17),
        'adha_start': (5, 18),
        'adha_days': 3,
        'hijri_new_year': (6, 6),
        'mawlid': (8, 15),
    },
}


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta

    return d + timedelta(days=n)


def _uae_rows(year: int) -> list[tuple[date, str]]:
    rows: list[tuple[date, str]] = [
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 12, 1), 'Commemoration Day'),
        (date(year, 12, 2), 'UAE National Day'),
        (date(year, 12, 3), 'UAE National Day (additional)'),
    ]
    p = _ISLAMIC_PRESETS.get(year)
    if not p:
        return rows
    m0, d0 = p['fitr_start']
    for i in range(p['fitr_days']):
        dd = _add_days(date(year, m0, d0), i)
        rows.append((dd, f'Eid al-Fitr (Day {i + 1})'))
    am, ad = p['arafat']
    rows.append((date(year, am, ad), 'Arafat Day'))
    m1, d1 = p['adha_start']
    for i in range(p['adha_days']):
        dd = _add_days(date(year, m1, d1), i)
        rows.append((dd, f'Eid al-Adha (Day {i + 1})'))
    hm, hd = p['hijri_new_year']
    rows.append((date(year, hm, hd), 'Islamic New Year (Hijri)'))
    mm, md = p['mawlid']
    rows.append((date(year, mm, md), "Prophet Muhammad's Birthday (PBUH)"))
    rows.sort(key=lambda x: x[0])
    return rows


def _ksa_rows(year: int) -> list[tuple[date, str]]:
    rows: list[tuple[date, str]] = [
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 2, 22), 'Saudi Founding Day'),
        (date(year, 9, 23), 'Saudi National Day'),
    ]
    p = _ISLAMIC_PRESETS.get(year)
    if not p:
        return rows
    m0, d0 = p['fitr_start']
    for i in range(p['fitr_days']):
        dd = _add_days(date(year, m0, d0), i)
        rows.append((dd, f'Eid al-Fitr (Day {i + 1})'))
    am, ad = p['arafat']
    rows.append((date(year, am, ad), 'Arafat Day'))
    m1, d1 = p['adha_start']
    for i in range(p['adha_days']):
        dd = _add_days(date(year, m1, d1), i)
        rows.append((dd, f'Eid al-Adha (Day {i + 1})'))
    hm, hd = p['hijri_new_year']
    rows.append((date(year, hm, hd), 'Islamic New Year (Hijri)'))
    mm, md = p['mawlid']
    rows.append((date(year, mm, md), "Prophet Muhammad's Birthday (PBUH)"))
    rows.sort(key=lambda x: x[0])
    return rows


def holiday_seed_rows_for_year(year: int) -> list[tuple[date, str, str]]:
    """(date, name, location) with location only 'uae' or 'ksa'."""
    rows: list[tuple[date, str, str]] = []
    for d, name in _uae_rows(year):
        rows.append((d, name, 'uae'))
    for d, name in _ksa_rows(year):
        rows.append((d, name, 'ksa'))
    return rows


def seed_public_holidays(HolidayModel, year: int) -> int:
    """Idempotent get_or_create; returns count of newly created rows."""
    n_created = 0
    for d, name, location in holiday_seed_rows_for_year(year):
        _, created = HolidayModel.objects.get_or_create(
            date=d,
            name=name,
            location=location,
            defaults={'is_recurring': False, 'is_active': True},
        )
        if created:
            n_created += 1
    return n_created


class Command(BaseCommand):
    help = 'Insert UAE-only and KSA-only public holiday rows (per-year Islamic presets in this file).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            default=2026,
            help='Calendar year to seed (default: 2026)',
        )

    def handle(self, *args, **options):
        y = int(options['year'])
        created = seed_public_holidays(Holiday, y)
        total = len(holiday_seed_rows_for_year(y))
        if y not in _ISLAMIC_PRESETS:
            self.stdout.write(
                self.style.WARNING(
                    f'Year {y}: only fixed national/Gregorian dates were seeded. '
                    f'Add an entry to _ISLAMIC_PRESETS in setup_holidays.py or create Eid rows via the admin UI.'
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Public holidays for {y}: {created} new rows ({total} definitions; UAE + KSA separate).'
            )
        )
