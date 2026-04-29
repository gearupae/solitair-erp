"""Idempotent demo rows for HR only (companies, org, employees, leave, templates, compliance stubs)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hr.models import (
    Department,
    Designation,
    Employee,
    KSACompliance,
    LeaveBalance,
    LeaveType,
    PayrollTemplate,
    UAECompliance,
)
from apps.hr.payroll_allowances import normalize_template_allowance_lines_json
from apps.settings_app.models import Company


class Command(BaseCommand):
    help = 'Create or refresh a small HR-only demo dataset (safe to run multiple times).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            default=None,
            help='Leave balance year (default: current year)',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        year = options['year'] or date.today().year
        today = date.today()

        co_uae, _ = Company.objects.get_or_create(
            name='Demo HR Entity (UAE)',
            defaults={
                'country': 'uae',
                'trade_license_number': 'DEMO-UAE-TL-001',
                'mol_number': '1234567',
                'address': 'Demo address, Dubai',
            },
        )
        co_ksa, _ = Company.objects.get_or_create(
            name='Demo HR Entity (KSA)',
            defaults={
                'country': 'ksa',
                'trade_license_number': 'DEMO-KSA-CR-001',
                'address': 'Demo address, Riyadh',
            },
        )

        dept, _ = Department.objects.get_or_create(
            code='DEMO-GU-HR-DEPT',
            defaults={'name': 'Demo HR Department'},
        )
        desig, _ = Designation.objects.get_or_create(
            name='Demo HR Specialist',
            department=dept,
            defaults={},
        )

        lt_annual, _ = LeaveType.objects.get_or_create(
            code='DEMO-GU-ANNUAL',
            defaults={
                'name': 'Demo Annual Leave',
                'days_allowed': 30,
                'location': 'both',
                'description': 'Seeded for demos only.',
            },
        )

        emp_uae, created_uae = Employee.objects.get_or_create(
            employee_code='DEMO-GU-UAE-01',
            defaults={
                'first_name': 'Demo',
                'last_name': 'Employee UAE',
                'email': 'demo.uae@example.invalid',
                'phone': '+971500000001',
                'gender': 'male',
                'department': dept,
                'designation': desig,
                'date_of_joining': today.replace(month=1, day=15),
                'status': 'active',
                'basic_salary': Decimal('8000.00'),
                'company': co_uae,
                'location': 'uae',
                'emirates_id': '784-DEMO-0000000-1',
                'visa_number': 'DEMO-VISA-UAE-1',
                'visa_expiry': today.replace(year=today.year + 1),
            },
        )
        if not created_uae:
            Employee.objects.filter(pk=emp_uae.pk).update(
                department_id=dept.pk,
                designation_id=desig.pk,
                company_id=co_uae.pk,
                location='uae',
            )
            emp_uae.refresh_from_db()

        emp_ksa, created_ksa = Employee.objects.get_or_create(
            employee_code='DEMO-GU-KSA-01',
            defaults={
                'first_name': 'Demo',
                'last_name': 'Employee KSA',
                'email': 'demo.ksa@example.invalid',
                'phone': '+966500000001',
                'gender': 'male',
                'department': dept,
                'designation': desig,
                'date_of_joining': today.replace(month=2, day=1),
                'status': 'active',
                'basic_salary': Decimal('9000.00'),
                'company': co_ksa,
                'location': 'ksa',
            },
        )
        if not created_ksa:
            Employee.objects.filter(pk=emp_ksa.pk).update(
                department_id=dept.pk,
                designation_id=desig.pk,
                company_id=co_ksa.pk,
                location='ksa',
            )
            emp_ksa.refresh_from_db()

        for emp in (emp_uae, emp_ksa):
            LeaveBalance.objects.get_or_create(
                employee=emp,
                leave_type=lt_annual,
                year=year,
                defaults={
                    'entitled_days': Decimal('22.00'),
                    'used_days': Decimal('0.00'),
                    'pending_days': Decimal('0.00'),
                    'carried_forward': Decimal('0.00'),
                },
            )

        lines_uae = normalize_template_allowance_lines_json(
            [
                {'code': 'HOUSING', 'description': 'Housing', 'amount': '2500.00'},
                {'code': 'TRANSPORT', 'description': 'Transport', 'amount': '800.00'},
            ]
        )
        tmpl_uae, _ = PayrollTemplate.objects.get_or_create(
            name='Demo salary template (UAE entity)',
            company=co_uae,
            defaults={
                'location': PayrollTemplate.LOCATION_UAE,
                'basic_salary': Decimal('8000.00'),
                'allowance_lines': lines_uae,
                'is_active': True,
            },
        )
        if tmpl_uae.allowance_lines != lines_uae:
            tmpl_uae.allowance_lines = lines_uae
            tmpl_uae.basic_salary = Decimal('8000.00')
            tmpl_uae.save(update_fields=['allowance_lines', 'basic_salary', 'updated_at'])

        lines_ksa = normalize_template_allowance_lines_json(
            [{'code': 'HOUSING', 'description': 'Housing', 'amount': '2000.00'}]
        )
        tmpl_ksa, _ = PayrollTemplate.objects.get_or_create(
            name='Demo salary template (KSA entity)',
            company=co_ksa,
            defaults={
                'location': PayrollTemplate.LOCATION_KSA,
                'basic_salary': Decimal('9000.00'),
                'allowance_lines': lines_ksa,
                'is_active': True,
            },
        )
        if tmpl_ksa.allowance_lines != lines_ksa:
            tmpl_ksa.allowance_lines = lines_ksa
            tmpl_ksa.basic_salary = Decimal('9000.00')
            tmpl_ksa.save(update_fields=['allowance_lines', 'basic_salary', 'updated_at'])

        UAECompliance.objects.get_or_create(
            employee=emp_uae,
            defaults={
                'visa_type': 'employment',
                'emirates_id_expiry': today.replace(year=today.year + 2),
                'iloe_applicable': True,
                'gratuity_applicable': True,
            },
        )

        KSACompliance.objects.get_or_create(
            employee=emp_ksa,
            defaults={
                'iqama_number': '123456789',
                'iqama_expiry': today.replace(year=today.year + 1),
                'iqama_profession': 'Demo occupation',
                'nationality': 'non_saudi',
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'HR demo seed OK (year={year}). '
                f'Companies: {co_uae.pk}, {co_ksa.pk}; employees: {emp_uae.employee_code}, {emp_ksa.employee_code}.'
            )
        )
