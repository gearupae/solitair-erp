"""Seed UAE leave types (idempotent — safe to re-run)."""
from django.core.management.base import BaseCommand

from apps.hr.models import LeaveType


def _common_defaults():
    return dict(is_active=True)


# Shared with migration 0024 — keep in sync when adding types.
LEAVE_TYPE_SEED_ROWS = [
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
    dict(
        code='UAE_MARRIAGE',
        name='Marriage Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=5,
        probation_allowed=True,
        description='Paid marriage leave per company policy / MOHRE guidelines.',
    ),
    dict(
        code='UAE_EMERGENCY',
        name='Emergency Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=5,
        probation_allowed=True,
        description='Short-notice emergencies (policy cap).',
    ),
    dict(
        code='UAE_FAMILY_CARE',
        name='Family Care Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=7,
        probation_allowed=True,
        description='Care for ill or dependent family member; HR may require proof.',
    ),
    dict(
        code='UAE_SICK_CHILD',
        name='Sick Child Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=3,
        probation_allowed=True,
        description='Paid leave to care for a sick child (annual cap per policy).',
    ),
    dict(
        code='UAE_ADOPTION',
        name='Adoption Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=14,
        probation_allowed=False,
        description='Leave for adoptive parents; align days with internal HR policy.',
    ),
    dict(
        code='UAE_NURSING',
        name='Nursing / Breastfeeding Break Leave (UAE)',
        location='uae',
        pay_type='full',
        days_allowed=None,
        gender_restricted='female',
        is_gender_specific=True,
        gender_required='female',
        probation_allowed=True,
        description='Reduced hours / nursing support; days policy-driven if tracked as leave.',
    ),
]


def seed_leave_types(LeaveTypeModel):
    """Upsert UAE seed rows; remove non-UAE catalog entries."""
    base = _common_defaults()
    for row in LEAVE_TYPE_SEED_ROWS:
        r = dict(row)
        code = r.pop('code')
        LeaveTypeModel.objects.update_or_create(code=code, defaults={**base, **r})
    LeaveTypeModel.objects.exclude(location='uae').delete()


class Command(BaseCommand):
    help = 'Create or update default UAE leave types (Federal Decree 33 baseline).'

    def handle(self, *args, **options):
        seed_leave_types(LeaveType)
        self.stdout.write(self.style.SUCCESS(f'Upserted {len(LEAVE_TYPE_SEED_ROWS)} UAE leave types.'))
