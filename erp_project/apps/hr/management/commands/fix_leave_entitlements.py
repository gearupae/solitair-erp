"""Update LeaveType rows with UAE/KSA legal baseline entitlements (match by code)."""
from django.core.management.base import BaseCommand

from apps.hr.models import LeaveType


ROWS = [
    (
        'UAE_ANNUAL',
        {
            'name': 'Annual Leave (UAE)',
            'days_allowed': 30,
            'location': 'uae',
            'pay_type': 'full',
            'probation_allowed': False,
            'min_service_days': 365,
            'carry_forward_allowed': True,
            'carry_forward_cap': 15,
            'description': (
                'Annual Leave UAE: up to 30 days after 1 year; 2 days/month after 6 months (180–364 days); '
                'carry-forward capped at 15 days.'
            ),
        },
    ),
    (
        'UAE_SICK',
        {
            'name': 'Sick Leave (UAE)',
            'days_allowed': 90,
            'location': 'uae',
            'pay_type': 'tiered',
            'probation_allowed': False,
            'requires_medical_certificate': True,
            'description': 'Tiered sick UAE: days 1–15 full; 16–45 half pay; 46–90 unpaid.',
        },
    ),
    (
        'UAE_MATERNITY',
        {
            'name': 'Maternity Leave (UAE)',
            'days_allowed': 60,
            'location': 'uae',
            'pay_type': 'tiered',
            'gender_restricted': 'female',
            'is_gender_specific': True,
            'gender_required': 'female',
            'probation_allowed': False,
            'description': 'Tiered maternity UAE: days 1–45 full pay; 46–60 half pay.',
        },
    ),
    (
        'UAE_PATERNITY',
        {
            'name': 'Paternity Leave (UAE)',
            'days_allowed': 5,
            'location': 'uae',
            'pay_type': 'full',
            'gender_restricted': 'male',
            'probation_allowed': False,
        },
    ),
    (
        'UAE_BEREAVEMENT',
        {
            'name': 'Bereavement Leave (UAE)',
            'days_allowed': 5,
            'location': 'uae',
            'pay_type': 'full',
            'probation_allowed': True,
        },
    ),
    (
        'UAE_HAJJ',
        {
            'name': 'Hajj Leave (UAE)',
            'days_allowed': 30,
            'location': 'uae',
            'pay_type': 'unpaid',
            'once_in_service': True,
            'min_service_days': 730,
            'religion_restricted': True,
            'probation_allowed': False,
            'is_paid': False,
        },
    ),
    (
        'UAE_STUDY',
        {
            'name': 'Study Leave (UAE)',
            'days_allowed': 10,
            'location': 'uae',
            'pay_type': 'full',
            'min_service_days': 730,
            'probation_allowed': False,
        },
    ),
    (
        'UAE_UNPAID',
        {
            'name': 'Unpaid Leave (UAE)',
            'days_allowed': None,
            'location': 'uae',
            'pay_type': 'unpaid',
            'probation_allowed': True,
            'is_paid': False,
        },
    ),
    (
        'KSA_ANNUAL',
        {
            'name': 'Annual Leave (KSA)',
            'days_allowed': 21,
            'location': 'ksa',
            'pay_type': 'full',
            'probation_allowed': False,
            'min_service_days': 0,
            'carry_forward_allowed': True,
            'carry_forward_cap': 30,
            'description': 'KSA annual: 21 days if service < 5 years; 30 days from year 5.',
        },
    ),
    (
        'KSA_SICK',
        {
            'name': 'Sick Leave (KSA)',
            'days_allowed': 120,
            'location': 'ksa',
            'pay_type': 'tiered',
            'probation_allowed': False,
            'requires_medical_certificate': True,
            'description': 'KSA sick tiered: days 1–30 full; 31–90 75%; 91–120 unpaid.',
        },
    ),
    (
        'KSA_MATERNITY',
        {
            'name': 'Maternity Leave (KSA)',
            'days_allowed': 84,
            'location': 'ksa',
            'pay_type': 'full',
            'gender_restricted': 'female',
            'is_gender_specific': True,
            'gender_required': 'female',
            'min_service_days': 0,
            'probation_allowed': False,
        },
    ),
    (
        'KSA_PATERNITY',
        {
            'name': 'Paternity Leave (KSA)',
            'days_allowed': 3,
            'location': 'ksa',
            'pay_type': 'full',
            'gender_restricted': 'male',
            'probation_allowed': False,
        },
    ),
    (
        'KSA_BEREAVEMENT',
        {
            'name': 'Bereavement Leave (KSA)',
            'days_allowed': 5,
            'location': 'ksa',
            'pay_type': 'full',
            'probation_allowed': True,
        },
    ),
    (
        'KSA_MARRIAGE',
        {
            'name': 'Marriage Leave (KSA)',
            'days_allowed': 5,
            'location': 'ksa',
            'pay_type': 'full',
            'probation_allowed': True,
        },
    ),
    (
        'KSA_HAJJ',
        {
            'name': 'Hajj Leave (KSA)',
            'days_allowed': 15,
            'location': 'ksa',
            'pay_type': 'full',
            'once_in_service': True,
            'min_service_days': 730,
            'religion_restricted': True,
            'probation_allowed': False,
        },
    ),
    (
        'KSA_IDDAH',
        {
            'name': 'Iddah Leave (KSA)',
            'days_allowed': 130,
            'location': 'ksa',
            'pay_type': 'full',
            'gender_restricted': 'female',
            'religion_restricted': True,
            'probation_allowed': False,
        },
    ),
    (
        'KSA_UNPAID',
        {
            'name': 'Unpaid Leave (KSA)',
            'days_allowed': None,
            'location': 'ksa',
            'pay_type': 'unpaid',
            'probation_allowed': True,
            'is_paid': False,
        },
    ),
]


class Command(BaseCommand):
    help = 'Fix LeaveType entitlements (UAE/KSA legal baseline). Safe to re-run.'

    def handle(self, *args, **options):
        from apps.hr.leave_balance_service import sync_all_employees_for_leave_type

        for code, defaults in ROWS:
            d = {**defaults, 'is_active': True}
            lt, _ = LeaveType.objects.update_or_create(code=code, defaults=d)
            sync_all_employees_for_leave_type(lt.pk)
            self.stdout.write(self.style.SUCCESS(f'Updated {code} (pk={lt.pk})'))

        self.stdout.write(self.style.SUCCESS(f'Done. Upserted {len(ROWS)} leave types.'))
