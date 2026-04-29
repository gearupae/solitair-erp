"""Create/update LeaveBalance rows for a calendar year (cron Jan 1)."""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.hr.models import Employee, LeaveBalance, LeaveType


class Command(BaseCommand):
    help = 'Generate yearly leave balance shells and baseline entitled days for active employees.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=None)

    def handle(self, *args, **options):
        year = options['year'] or date.today().year
        annual_codes = {'UAE_ANNUAL': Decimal('30'), 'KSA_ANNUAL': Decimal('21')}
        employees = Employee.objects.filter(is_active=True, location__in=['uae', 'ksa'])
        new_rows = 0
        for emp in employees:
            code = 'UAE_ANNUAL' if emp.location == 'uae' else 'KSA_ANNUAL'
            lt = LeaveType.objects.filter(code=code, is_active=True).first()
            if not lt:
                continue
            entitled = annual_codes.get(code, Decimal('0'))
            if code == 'KSA_ANNUAL' and emp.date_of_joining:
                from dateutil.relativedelta import relativedelta

                yrs = relativedelta(date(year, 12, 31), emp.date_of_joining).years
                entitled = Decimal('30') if yrs >= 5 else Decimal('21')
            _lb, created = LeaveBalance.objects.get_or_create(
                employee=emp,
                leave_type=lt,
                year=year,
                defaults={
                    'entitled_days': entitled,
                    'carried_forward': Decimal('0'),
                },
            )
            if created:
                new_rows += 1
        self.stdout.write(
            self.style.SUCCESS(
                f'Year {year}: scanned {employees.count()} employees; created {new_rows} new annual balance rows.'
            )
        )
