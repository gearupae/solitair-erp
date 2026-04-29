"""Seed UAE/KSA leave types (idempotent — safe to re-run)."""
from django.core.management.base import BaseCommand

from apps.hr.models import LeaveType


def _common_defaults():
    return dict(is_active=True)


class Command(BaseCommand):
    help = 'Create or update default UAE/KSA leave types (Federal Decree 33 / Saudi Labour Law baseline).'

    def handle(self, *args, **options):
        rows = [
            # UAE
            dict(
                code='UAE_ANNUAL',
                name='Annual Leave (UAE)',
                location='uae',
                pay_type='full',
                days_allowed=30,
                probation_allowed=True,
                carry_forward_allowed=True,
                description='30 days/year after 1 year service; probation accrual handled in balance engine.',
            ),
            dict(
                code='UAE_SICK',
                name='Sick Leave (UAE)',
                location='uae',
                pay_type='tiered',
                days_allowed=90,
                requires_medical_certificate=True,
                probation_allowed=True,
            ),
            dict(
                code='UAE_MATERNITY',
                name='Maternity Leave (UAE)',
                location='uae',
                pay_type='tiered',
                days_allowed=60,
                gender_restricted='female',
                is_gender_specific=True,
                gender_required='female',
                probation_allowed=False,
            ),
            dict(
                code='UAE_PATERNITY',
                name='Paternity Leave (UAE)',
                location='uae',
                pay_type='full',
                days_allowed=5,
                gender_restricted='male',
                probation_allowed=False,
            ),
            dict(
                code='UAE_BEREAVEMENT',
                name='Bereavement Leave (UAE)',
                location='uae',
                pay_type='full',
                days_allowed=5,
                probation_allowed=True,
            ),
            dict(
                code='UAE_HAJJ',
                name='Hajj Leave (UAE)',
                location='uae',
                pay_type='unpaid',
                days_allowed=30,
                once_in_service=True,
                religion_restricted=True,
                probation_allowed=False,
            ),
            dict(
                code='UAE_STUDY',
                name='Study Leave (UAE)',
                location='uae',
                pay_type='full',
                days_allowed=10,
                min_service_days=730,
                probation_allowed=False,
            ),
            dict(
                code='UAE_UNPAID',
                name='Unpaid Leave (UAE)',
                location='uae',
                pay_type='unpaid',
                days_allowed=None,
                probation_allowed=True,
            ),
            dict(
                code='UAE_WORK_INJURY',
                name='Work Injury Leave (UAE)',
                location='uae',
                pay_type='full',
                days_allowed=None,
                requires_medical_certificate=True,
                probation_allowed=True,
            ),
            # KSA
            dict(
                code='KSA_ANNUAL',
                name='Annual Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=21,
                probation_allowed=True,
                carry_forward_allowed=True,
                description='21 days (<5 yrs service); escalates to 30 days via entitlement rules.',
            ),
            dict(
                code='KSA_SICK',
                name='Sick Leave (KSA)',
                location='ksa',
                pay_type='tiered',
                days_allowed=120,
                requires_medical_certificate=True,
                probation_allowed=True,
            ),
            dict(
                code='KSA_MATERNITY',
                name='Maternity Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=70,
                gender_restricted='female',
                is_gender_specific=True,
                gender_required='female',
                probation_allowed=False,
            ),
            dict(
                code='KSA_PATERNITY',
                name='Paternity Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=3,
                gender_restricted='male',
                probation_allowed=False,
            ),
            dict(
                code='KSA_BEREAVEMENT',
                name='Bereavement Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=5,
                probation_allowed=True,
            ),
            dict(
                code='KSA_HAJJ',
                name='Hajj Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=10,
                once_in_service=True,
                religion_restricted=True,
                probation_allowed=False,
            ),
            dict(
                code='KSA_IDDAH',
                name='Iddah Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=130,
                gender_restricted='female',
                religion_restricted=True,
                probation_allowed=False,
            ),
            dict(
                code='KSA_STUDY',
                name='Study / Exam Leave (KSA)',
                location='ksa',
                pay_type='full',
                days_allowed=10,
                probation_allowed=True,
            ),
            dict(
                code='KSA_UNPAID',
                name='Unpaid Leave (KSA)',
                location='ksa',
                pay_type='unpaid',
                days_allowed=None,
                probation_allowed=True,
            ),
        ]
        n = 0
        base = _common_defaults()
        for row in rows:
            code = row.pop('code')
            defaults = {**base, **row}
            LeaveType.objects.update_or_create(code=code, defaults=defaults)
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Upserted {n} leave types.'))
