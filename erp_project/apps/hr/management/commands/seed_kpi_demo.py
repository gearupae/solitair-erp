"""Seed KPI demo data: tasks, projects, remarks, sales/purchase departments."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.hr.models import Department, Designation, Employee, EmployeeRemark
from apps.hr.user_provisioning import sync_pending_employees_to_users

User = get_user_model()
PREFIX = 'KPI-DEMO'


class Command(BaseCommand):
    help = 'Seed demo KPI data (tasks, projects, HR points) for dashboard testing.'

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()

        dept_proj, _ = Department.objects.get_or_create(
            code=f'{PREFIX}-PROJ', defaults={'name': 'Projects & Operations'},
        )
        dept_sales, _ = Department.objects.get_or_create(
            code=f'{PREFIX}-SAL', defaults={'name': 'Sales'},
        )
        dept_pur, _ = Department.objects.get_or_create(
            code=f'{PREFIX}-PUR', defaults={'name': 'Purchase & Procurement'},
        )

        desig_pm, _ = Designation.objects.get_or_create(
            name=f'{PREFIX} Project Manager', department=dept_proj,
        )
        desig_eng, _ = Designation.objects.get_or_create(
            name=f'{PREFIX} Project Engineer', department=dept_proj,
        )
        desig_sales, _ = Designation.objects.get_or_create(
            name=f'{PREFIX} Sales Executive', department=dept_sales,
        )
        desig_buyer, _ = Designation.objects.get_or_create(
            name=f'{PREFIX} Buyer', department=dept_pur,
        )

        staff_specs = [
            ('01', 'Sultan', 'Al Kaabi', dept_proj, desig_pm, 'sultan.kpi@gearup.demo'),
            ('02', 'Hamad', 'Al Suwaidi', dept_proj, desig_eng, 'hamad.kpi@gearup.demo'),
            ('03', 'Layla', 'Al Mazrouei', dept_sales, desig_sales, 'layla.kpi@gearup.demo'),
            ('04', 'Faisal', 'Al Ketbi', dept_pur, desig_buyer, 'faisal.kpi@gearup.demo'),
        ]

        employees = []
        for seq, first, last, dept, desig, email in staff_specs:
            code = f'{PREFIX}-{seq}'
            emp, _ = Employee.objects.update_or_create(
                employee_code=code,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'department': dept,
                    'designation': desig,
                    'status': 'active',
                    'date_of_joining': date(2024, 1, 15),
                    'basic_salary': 15000,
                    'location': 'uae',
                },
            )
            employees.append(emp)

        sync_pending_employees_to_users(limit=50)
        for emp in employees:
            emp.refresh_from_db()
            if not emp.user_id:
                user, _ = User.objects.get_or_create(
                    username=emp.email,
                    defaults={
                        'email': emp.email,
                        'first_name': emp.first_name,
                        'last_name': emp.last_name,
                        'is_active': True,
                    },
                )
                emp.user = user
                emp.save(update_fields=['user'])

        from apps.projects.models import Project, Task

        pm, eng, sales_emp, buyer = employees
        pm_user = pm.user
        eng_user = eng.user

        project, _ = Project.objects.get_or_create(
            project_code=f'{PREFIX}-PRJ-001',
            defaults={
                'name': 'KPI Demo — Fire safety retrofit',
                'status': 'ongoing',
                'manager': pm_user,
                'start_date': today - timedelta(days=60),
                'end_date': today + timedelta(days=30),
            },
        )
        if pm_user:
            project.members.add(pm_user)
        if eng_user:
            project.members.add(eng_user)
            project.technicians.add(eng_user)

        Project.objects.get_or_create(
            project_code=f'{PREFIX}-PRJ-002',
            defaults={
                'name': 'KPI Demo — AMC maintenance',
                'status': 'completed',
                'manager': pm_user,
                'start_date': today - timedelta(days=120),
                'end_date': today - timedelta(days=10),
            },
        )

        task_specs = [
            (eng_user, 'Install detectors — Block A', 'completed', today - timedelta(days=20), today - timedelta(days=5)),
            (eng_user, 'Cable routing — Block B', 'completed', today - timedelta(days=15), today - timedelta(days=2)),
            (eng_user, 'Panel commissioning', 'in_progress', today - timedelta(days=10), today + timedelta(days=5)),
            (eng_user, 'Client handover docs', 'pending', today, today + timedelta(days=14)),
            (eng_user, 'Overdue snag list', 'in_progress', today - timedelta(days=30), today - timedelta(days=7)),
            (pm_user, 'Weekly progress report', 'completed', today - timedelta(days=7), today - timedelta(days=1)),
            (pm_user, 'Vendor coordination', 'pending', today, today + timedelta(days=3)),
        ]

        task_count = 0
        for user, name, status, start, due in task_specs:
            if not user:
                continue
            _, created = Task.objects.get_or_create(
                project=project,
                name=f'{PREFIX} {name}',
                defaults={
                    'assigned_to': user,
                    'status': status,
                    'start_date': start,
                    'due_date': due,
                },
            )
            if created:
                task_count += 1

        remark_specs = [
            (pm, 'plus', 'Delivered milestone ahead of client deadline.'),
            (pm, 'plus', 'Strong coordination with procurement.'),
            (eng, 'negative', 'Two tasks completed past due date — needs tighter follow-up.'),
            (eng, 'plus', 'Quality of site work praised by client.'),
            (sales_emp, 'plus', 'Closed two leads this quarter.'),
            (buyer, 'negative', 'One PO delayed due to missing vendor quote.'),
        ]
        remark_count = 0
        for emp, rtype, body in remark_specs:
            if EmployeeRemark.objects.filter(employee=emp, body=body).exists():
                continue
            EmployeeRemark.objects.create(
                employee=emp, remark_type=rtype, body=body,
            )
            remark_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'KPI demo seed OK: {len(employees)} staff, {task_count} new tasks, '
                f'{remark_count} remarks. Open /hr/kpi/ to review.'
            )
        )
