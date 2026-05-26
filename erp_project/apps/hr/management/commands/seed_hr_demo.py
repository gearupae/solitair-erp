"""Idempotent demo rows for HR (org, employees, leave, attendance, payroll)."""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hr.models import (
    Department,
    Designation,
    Employee,
    KSACompliance,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Payroll,
    PayrollTemplate,
    UAECompliance,
)
from apps.hr.models_extended import AttendanceRecord
from apps.hr.payroll_allowances import normalize_template_allowance_lines_json
from apps.settings_app.models import Company

SEED_PREFIX = 'DEMO-AN'

DEPARTMENTS = [
    ('HR', 'Human Resources'),
    ('OPS', 'Operations'),
    ('FIN', 'Finance'),
    ('IT', 'Information Technology'),
    ('PROJ', 'Projects'),
]

DESIGNATIONS = [
    ('HR Manager', 'HR'),
    ('HR Executive', 'HR'),
    ('Operations Manager', 'OPS'),
    ('Field Technician', 'OPS'),
    ('Site Supervisor', 'OPS'),
    ('Accountant', 'FIN'),
    ('Finance Manager', 'FIN'),
    ('IT Support', 'IT'),
    ('Project Manager', 'PROJ'),
    ('Project Engineer', 'PROJ'),
]

EMPLOYEES = [
    ('001', 'Ahmed', 'Al Mansoori', 'male', 'HR', 'HR Manager', 22000),
    ('002', 'Fatima', 'Al Hashimi', 'female', 'HR', 'HR Executive', 12000),
    ('003', 'Khalid', 'Al Nuaimi', 'male', 'OPS', 'Operations Manager', 28000),
    ('004', 'Omar', 'Al Zaabi', 'male', 'OPS', 'Site Supervisor', 15000),
    ('005', 'Rashid', 'Al Ketbi', 'male', 'OPS', 'Field Technician', 9000),
    ('006', 'Hassan', 'Al Shamsi', 'male', 'OPS', 'Field Technician', 8500),
    ('007', 'Saeed', 'Al Dhaheri', 'male', 'FIN', 'Finance Manager', 25000),
    ('008', 'Mariam', 'Al Qasimi', 'female', 'FIN', 'Accountant', 11000),
    ('009', 'Youssef', 'Al Mazrouei', 'male', 'IT', 'IT Support', 13000),
    ('010', 'Sultan', 'Al Kaabi', 'male', 'PROJ', 'Project Manager', 26000),
    ('011', 'Hamad', 'Al Suwaidi', 'male', 'PROJ', 'Project Engineer', 14000),
    ('012', 'Nasser', 'Al Falasi', 'male', 'PROJ', 'Project Engineer', 13500),
]


class Command(BaseCommand):
    help = 'Create or refresh HR demo data (safe to run multiple times).'

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
            name='Al Najah Fire Safety (UAE)',
            defaults={
                'country': 'uae',
                'trade_license_number': 'DEMO-UAE-TL-001',
                'mol_number': '1234567',
                'address': 'Industrial Area, Dubai, UAE',
            },
        )

        dept_map = {}
        for code, name in DEPARTMENTS:
            dept, _ = Department.objects.get_or_create(code=f'{SEED_PREFIX}-{code}', defaults={'name': name})
            dept_map[code] = dept

        desig_map = {}
        for title, dept_code in DESIGNATIONS:
            desig, _ = Designation.objects.get_or_create(name=title, department=dept_map[dept_code])
            desig_map[title] = desig

        lt_annual = LeaveType.objects.filter(code='UAE_ANNUAL').first()
        if not lt_annual:
            lt_annual, _ = LeaveType.objects.get_or_create(
                code='DEMO-GU-ANNUAL',
                defaults={
                    'name': 'Demo Annual Leave',
                    'days_allowed': 30,
                    'location': 'both',
                    'description': 'Seeded for demos only.',
                },
            )

        lt_sick = LeaveType.objects.filter(code='UAE_SICK').first()

        employees = []
        for seq, first, last, gender, dept_code, desig_title, salary in EMPLOYEES:
            code = f'{SEED_PREFIX}-{seq}'
            join_month = max(1, (int(seq) % 12) or 1)
            emp, _ = Employee.objects.update_or_create(
                employee_code=code,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': f'{first.lower()}.{last.lower().replace(" ", "")}@alnajah.demo',
                    'phone': f'+97150{int(seq):07d}',
                    'gender': gender,
                    'department': dept_map[dept_code],
                    'designation': desig_map[desig_title],
                    'date_of_joining': date(2023, join_month, min(15, 28)),
                    'status': 'active',
                    'basic_salary': Decimal(str(salary)),
                    'company': co_uae,
                    'location': 'uae',
                    'emirates_id': f'784-DEMO-{seq.zfill(7)}-1',
                    'visa_number': f'DEMO-VISA-{seq}',
                    'visa_expiry': today.replace(year=today.year + 1),
                },
            )
            employees.append(emp)

            LeaveBalance.objects.get_or_create(
                employee=emp,
                leave_type=lt_annual,
                year=year,
                defaults={
                    'entitled_days': Decimal('30.00'),
                    'used_days': Decimal('2.00') if int(seq) % 3 == 0 else Decimal('0.00'),
                    'pending_days': Decimal('0.00'),
                    'carried_forward': Decimal('0.00'),
                },
            )

            UAECompliance.objects.get_or_create(
                employee=emp,
                defaults={
                    'visa_type': 'employment',
                    'emirates_id_expiry': today.replace(year=today.year + 2),
                    'iloe_applicable': True,
                    'gratuity_applicable': True,
                },
            )

        lines_uae = normalize_template_allowance_lines_json(
            [
                {'code': 'HOUSING', 'description': 'Housing', 'amount': '2500.00'},
                {'code': 'TRANSPORT', 'description': 'Transport', 'amount': '800.00'},
            ]
        )
        tmpl_uae, _ = PayrollTemplate.objects.get_or_create(
            name='Standard UAE package (demo)',
            company=co_uae,
            defaults={
                'location': PayrollTemplate.LOCATION_UAE,
                'basic_salary': Decimal('8000.00'),
                'allowance_lines': lines_uae,
                'is_active': True,
            },
        )
        Employee.objects.filter(employee_code__startswith=SEED_PREFIX).update(salary_template=tmpl_uae)

        leave_specs = [
            (employees[1], lt_annual, today + timedelta(days=14), today + timedelta(days=18), 'pending_manager', 'Family visit'),
            (employees[4], lt_annual, today + timedelta(days=7), today + timedelta(days=9), 'pending_hr', 'Personal leave'),
            (employees[7], lt_annual, today - timedelta(days=20), today - timedelta(days=18), 'approved', 'Approved annual leave'),
            (employees[10], lt_annual, today - timedelta(days=45), today - timedelta(days=42), 'approved', 'Project break'),
            (employees[3], lt_sick or lt_annual, today - timedelta(days=5), today - timedelta(days=4), 'rejected', 'Insufficient medical docs'),
        ]
        leave_count = 0
        for emp, lt, start, end, status, reason in leave_specs:
            if not lt:
                continue
            ref = f'LR-{SEED_PREFIX}-{emp.employee_code[-3:]}-{start:%Y%m%d}'
            _, created = LeaveRequest.objects.get_or_create(
                reference_number=ref,
                defaults={
                    'employee': emp,
                    'leave_type': lt,
                    'start_date': start,
                    'end_date': end,
                    'reason': reason,
                    'status': status,
                },
            )
            if created:
                leave_count += 1

        attendance_count = 0
        for emp in employees:
            for offset in range(14, 0, -1):
                day = today - timedelta(days=offset)
                if day.weekday() >= 5:
                    continue
                status = 'present'
                check_in = time(8, 55)
                check_out = time(18, 5)
                if int(emp.employee_code[-3:]) % 7 == offset % 7:
                    status = 'late'
                    check_in = time(9, 25)
                elif int(emp.employee_code[-3:]) % 11 == offset % 11:
                    status = 'absent'
                    check_in = None
                    check_out = None
                _, created = AttendanceRecord.objects.get_or_create(
                    employee=emp,
                    date=day,
                    defaults={
                        'check_in': check_in,
                        'check_out': check_out,
                        'status': status,
                        'source': 'manual',
                        'notes': 'Demo attendance seed',
                    },
                )
                if created:
                    attendance_count += 1

        payroll_count = 0
        for month_offset in (0, 1):
            month_date = date(today.year, today.month, 1) - timedelta(days=month_offset * 28)
            month_date = month_date.replace(day=1)
            for emp in employees:
                allowances = (emp.basic_salary * Decimal('0.20')).quantize(Decimal('0.01'))
                gross = emp.basic_salary + allowances
                _, created = Payroll.objects.get_or_create(
                    employee=emp,
                    month=month_date,
                    defaults={
                        'company': co_uae,
                        'basic_salary': emp.basic_salary,
                        'allowances': allowances,
                        'gross_salary': gross,
                        'deductions': Decimal('0.00'),
                        'net_salary': gross,
                        'status': 'draft' if month_offset == 0 else 'processed',
                    },
                )
                if created:
                    payroll_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'HR demo seed OK (year={year}). '
                f'{len(employees)} employees, {leave_count} leave requests, '
                f'{attendance_count} attendance rows, {payroll_count} payroll rows.'
            )
        )
