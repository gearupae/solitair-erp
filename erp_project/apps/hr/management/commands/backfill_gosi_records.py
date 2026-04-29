"""Backfill GOSIRecord for processed/paid KSA payrolls missing a record."""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from apps.hr.gosi_export_service import gosi_contribution_rates, nationality_label, sync_gosi_record_for_payroll
from apps.hr.models import Payroll
from apps.hr.models_extended import GOSIRecord


class Command(BaseCommand):
    help = (
        'Create missing GOSIRecord rows for processed/paid KSA payrolls (GOSI applicable). '
        'Usage: python manage.py backfill_gosi_records [--month=11 --year=2024] [--verify]'
    )

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, default=None, help='Calendar month 1-12 (optional)')
        parser.add_argument('--year', type=int, default=None, help='Year (optional)')
        parser.add_argument(
            '--verify',
            action='store_true',
            help='Print expected GOSI vs stored record for each eligible payroll (no DB writes)',
        )

    def handle(self, *args, **options):
        month: int | None = options.get('month')
        year: int | None = options.get('year')
        verify: bool = options.get('verify')

        qs = (
            Payroll.objects.filter(
                status__in=['processed', 'paid'],
                is_active=True,
                employee__location='ksa',
            )
            .select_related('employee', 'employee__ksa_compliance', 'company')
            .order_by('month', 'employee__employee_code')
        )
        if year is not None:
            qs = qs.filter(month__year=year)
        if month is not None:
            qs = qs.filter(month__month=month)

        if verify:
            self._run_verify(qs)
            return

        missing = qs.annotate(_g=Exists(GOSIRecord.objects.filter(payroll_id=OuterRef('pk')))).filter(_g=False)
        count = 0
        skipped = 0
        for p in missing.iterator():
            kc = getattr(p.employee, 'ksa_compliance', None)
            if not kc or not kc.gosi_applicable:
                skipped += 1
                continue
            if sync_gosi_record_for_payroll(p):
                count += 1
                self.stdout.write(self.style.SUCCESS(f'GOSIRecord created for payroll {p.pk} {p.employee.full_name}'))
        self.stdout.write(self.style.SUCCESS(f'Done. Created {count} record(s). Skipped (no compliance): {skipped}'))

    def _run_verify(self, qs):
        for p in qs.iterator():
            emp = p.employee
            kc = getattr(emp, 'ksa_compliance', None)
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(f'--- Payroll #{p.pk} | {emp.full_name} | {p.month:%Y-%m} | status={p.status}'))
            if (emp.location or '').lower() != 'ksa':
                self.stdout.write('  (skip: employee location is not ksa)')
                continue
            if not kc or not kc.gosi_applicable:
                self.stdout.write('  (skip: no KSA compliance or GOSI not applicable)')
                continue

            basic = p.basic_salary or Decimal('0')
            nat = (kc.nationality or 'non_saudi').lower()
            emp_rate, er_rate = gosi_contribution_rates(nat)
            emp_c = (basic * emp_rate).quantize(Decimal('0.01'))
            er_c = (basic * er_rate).quantize(Decimal('0.01'))
            total = (emp_c + er_c).quantize(Decimal('0.01'))

            self.stdout.write(f'  Nationality: {nationality_label(nat)}')
            self.stdout.write(f'  Basic: SAR {basic:,.2f}')
            if nat == 'saudi':
                self.stdout.write(f'  Employee GOSI (10%): SAR {emp_c:,.2f} ✅')
                self.stdout.write(f'  Employer GOSI (12%): SAR {er_c:,.2f} ✅')
            else:
                self.stdout.write(f'  Employee GOSI (0%): SAR {emp_c:,.2f} ✅')
                self.stdout.write(f'  Employer GOSI (2% hazard): SAR {er_c:,.2f} ✅')
            self.stdout.write(f'  Total: SAR {total:,.2f} ✅')

            gr = GOSIRecord.objects.filter(payroll=p).first()
            if gr:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  GOSIRecord exists: YES ✅ (ee={gr.employee_contribution}, er={gr.employer_contribution})'
                    )
                )
            else:
                self.stdout.write(self.style.ERROR('  GOSIRecord exists: NO ❌'))
