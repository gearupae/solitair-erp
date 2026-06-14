"""
Seed dummy leads, projects, and estimates for AI forecasting reports.

Safe to re-run: uses DEMO-FC-* markers in notes / names.

  python manage.py seed_forecasting_demo
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()

SEED_TAG = 'DEMO-FC'
SEED_NOTE = 'Seeded by seed_forecasting_demo'

LEADS = [
    # seq, company, stage, source keyword in notes, job_type, scope, days_ago (within current month)
    ('01', 'Palm Jumeirah Tower FM', 'hot', 'google', ['fire_protection_system'], 'project', 5),
    ('02', 'Marina Walk Retail LLC', 'warm', 'whatsapp', ['cctv'], 'amc', 12),
    ('03', 'Abu Dhabi Industrial Warehouse', 'cold', 'reference', ['gas_protection_system'], 'maintenance', 11),
    ('04', 'DIFC Grade A Office', 'hot', 'facebook', ['fire_protection_system', 'cctv'], 'project', 3),
    ('05', 'JLT Restaurant Group', 'warm', 'walk-in', ['fire_protection_system'], 'amc', 13),
    ('06', 'Sharjah Private Hospital', 'hot', 'google', ['fire_protection_system'], 'project', 8),
    ('07', 'Ajman School Campus', 'cold', 'referral', ['gas_protection_system'], 'maintenance', 14),
    ('08', 'Business Bay Hotel', 'warm', 'whatsapp', ['cctv'], 'project', 13),
    ('09', 'Dubai Silicon Oasis Tech Park', 'hot', 'google', ['fire_protection_system'], 'project', 2),
    ('10', 'Al Barsha Villa Compound', 'cold', 'physical', ['fire_protection_system'], 'amc', 9),
]

COMPLETED_PROJECTS = [
    # seq, name, category, sub_category, contract, est_cost, actual_cost
    ('01', 'Fire Alarm Retrofit – Deira Tower', 'fire', 'project', 185000, 142000, 158000),
    ('02', 'AMC Year 1 – Marina Hotel', 'fire', 'amc', 96000, 72000, 69500),
    ('03', 'CCTV Upgrade – Business Bay', 'cctv', 'project', 74000, 58000, 71000),
    ('04', 'Gas Suppression – Al Quoz', 'gas', 'maintenance', 52000, 41000, 48500),
    ('05', 'Emergency Lighting – Sharjah Mall', 'fire', 'rectification', 88000, 67000, 82000),
]

ACTIVE_ESTIMATES = [
    # seq, lead_or_cust_ref suffix, status, occupancy, work_type, days_ago
    ('04', '04', 'under_negotiation', 'commercial', 'installation_with_amc', 4),
    ('05', '05', 'sent', 'restaurants', 'amc', 10),
    ('06', '06', 'approved', 'commercial', 'installation_without_amc', 6),
    ('07', '07', 'sent', 'factories_industries', 'maintenance', 14),
    ('08', '08', 'under_negotiation', 'commercial', 'installation_with_amc', 7),
    ('09', '09', 'approved', 'commercial', 'installation_without_amc', 2),
    ('10', '10', 'draft', 'villa', 'maintenance', 1),
]


class Command(BaseCommand):
    help = 'Seed leads, projects, and estimates for forecasting reports (idempotent)'

    @transaction.atomic
    def handle(self, *args, **options):
        admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_active=True).first()
        if not admin:
            self.stderr.write(self.style.ERROR('No active user found.'))
            return

        today = date.today()
        salespeople = list(
            __import__('apps.hr.models', fromlist=['Employee']).Employee.objects.filter(
                is_active=True,
            ).order_by('id')[:5]
        )

        counts = {}
        counts['leads'] = self._seed_leads(admin, today, salespeople)
        counts['lead_dates_refreshed'] = self._refresh_demo_lead_dates()
        counts['lead_estimates'] = self._seed_lead_estimates(admin, today)
        counts['completed_projects'] = self._seed_completed_projects(admin, today)
        counts['active_estimates'] = self._seed_active_estimates(admin, today)
        counts['project_activity'] = self._enrich_active_projects(admin, today)

        cache.clear()

        self.stdout.write(self.style.SUCCESS('\nForecasting demo seed complete:'))
        for key, val in counts.items():
            self.stdout.write(f'  {key}: {val}')

        self._print_report_counts(today)

    def _seed_marker(self, seq: str) -> str:
        return f'{SEED_NOTE} ref {SEED_TAG}-{seq}'

    def _get_stage(self, slug: str):
        from apps.crm.models import CrmLeadKanbanStage

        return CrmLeadKanbanStage.objects.filter(slug=slug, is_active=True).first()

    def _stamp_dates(self, model, pk, *, created_days_ago: int):
        when = timezone.make_aware(
            datetime.combine(date.today() - timedelta(days=created_days_ago), datetime.min.time())
        )
        model.objects.filter(pk=pk).update(created_at=when, updated_at=when)

    def _seed_leads(self, admin, today: date, salespeople) -> int:
        from apps.crm.models import Customer

        created = 0
        for idx, (seq, company, stage_slug, source, job_type, scope, days_ago) in enumerate(LEADS):
            marker = self._seed_marker(f'LEAD-{seq}')
            if Customer.objects.filter(notes__contains=marker).exists():
                continue

            stage = self._get_stage(stage_slug)
            sp = salespeople[idx % len(salespeople)] if salespeople else None
            lead = Customer.objects.create(
                name=f'Contact {seq}',
                company=f'[{SEED_TAG}] {company}',
                email=f'lead{seq}@forecast.demo',
                phone=f'+97150{int(seq):07d}',
                city='Dubai',
                country='United Arab Emirates',
                customer_type='lead',
                lead_kanban_stage=stage,
                assigned_salesperson=sp,
                job_type=job_type,
                scope=scope,
                status='active',
                notes=f'{marker}. Source: {source} inquiry for fire & safety works.',
                created_by=admin,
            )
            self._stamp_dates(Customer, lead.pk, created_days_ago=days_ago)
            created += 1
        return created

    def _refresh_demo_lead_dates(self) -> int:
        """Re-stamp DEMO-FC lead dates so they appear in the current-month report window."""
        from apps.crm.models import Customer

        updated = 0
        days_by_seq = {seq: days for seq, *_rest, days in LEADS}
        for seq, days_ago in days_by_seq.items():
            lead = Customer.objects.filter(
                customer_type='lead',
                notes__contains=self._seed_marker(f'LEAD-{seq}'),
            ).first()
            if not lead:
                continue
            self._stamp_dates(Customer, lead.pk, created_days_ago=days_ago)
            updated += 1
        return updated

    def _seed_lead_estimates(self, admin, today: date) -> int:
        from apps.crm.models import Customer
        from apps.sales.models import Estimate, EstimateItem

        tax_code = self._tax_code()
        created = 0
        for seq in ('01', '04', '06', '09'):
            marker = self._seed_marker(f'LEAD-EST-{seq}')
            if Estimate.objects.filter(notes__contains=marker).exists():
                continue

            lead = Customer.objects.filter(
                customer_type='lead',
                notes__contains=self._seed_marker(f'LEAD-{seq}'),
            ).first()
            if not lead:
                continue

            user = admin
            if lead.assigned_salesperson_id and lead.assigned_salesperson.user_id:
                user = lead.assigned_salesperson.user

            estimate = Estimate.objects.create(
                customer=lead,
                assigned_to=user,
                prepared_by=user.get_full_name() or user.username,
                date=today - timedelta(days=3),
                valid_until=today + timedelta(days=30),
                status='sent',
                type_of_occupancy='commercial',
                type_of_work='installation_with_amc',
                notes=marker,
                client_note='Demo quotation for lead forecasting.',
                created_by=admin,
            )
            self._add_estimate_lines(estimate, tax_code, admin, variant=int(seq))
            estimate.calculate_totals()
            created += 1
        return created

    def _seed_completed_projects(self, admin, today: date) -> int:
        from apps.crm.models import Customer
        from apps.projects.models import Project, ProjectExpense, Task
        from apps.sales.models import Estimate

        tax_code = self._tax_code()
        created = 0
        for seq, name, category, sub_category, contract, est_cost, actual_cost in COMPLETED_PROJECTS:
            marker = self._seed_marker(f'COMP-{seq}')
            if Project.objects.filter(description__contains=marker).exists():
                continue

            customer = Customer.objects.filter(customer_type='customer', is_active=True).order_by('pk').first()
            if not customer:
                customer = Customer.objects.filter(is_active=True).order_by('pk').first()

            start = today - timedelta(days=120)
            end = today - timedelta(days=15)
            project = Project.objects.create(
                name=f'[{SEED_TAG}] {name}',
                description=f'{marker} – completed project for sales learning.',
                customer=customer,
                manager=admin,
                status='completed',
                category=category,
                sub_category=sub_category,
                billing_type='fixed',
                budget=Decimal(str(est_cost)),
                estimated_cost=Decimal(str(est_cost)),
                contract_value=Decimal(str(contract)),
                total_expenses=Decimal(str(actual_cost)),
                total_revenue=Decimal(str(contract)),
                start_date=start,
                end_date=end,
                created_by=admin,
            )

            estimate = Estimate.objects.create(
                customer=customer,
                project=project,
                assigned_to=admin,
                prepared_by=admin.get_full_name() or admin.username,
                date=start,
                valid_until=start + timedelta(days=30),
                status='quotation_won',
                type_of_occupancy='commercial',
                type_of_work='installation_with_amc',
                notes=f'{marker} linked estimate',
                created_by=admin,
            )
            self._add_estimate_lines(estimate, tax_code, admin, variant=int(seq))
            estimate.calculate_totals()

            self._add_project_expenses(project, admin, actual_cost, est_cost, end)
            Task.objects.create(
                project=project,
                name='Final handover inspection',
                status='completed',
                estimated_hours=Decimal('16'),
                created_by=admin,
            )
            created += 1
        return created

    def _seed_active_estimates(self, admin, today: date) -> int:
        from apps.crm.models import Customer
        from apps.sales.models import Estimate

        tax_code = self._tax_code()
        created = 0
        for seq, lead_seq, status, occupancy, work_type, days_ago in ACTIVE_ESTIMATES:
            marker = self._seed_marker(f'EST-{seq}')
            if Estimate.objects.filter(notes__contains=marker).exists():
                continue

            lead = Customer.objects.filter(notes__contains=self._seed_marker(f'LEAD-{lead_seq}')).first()
            customer = lead or Customer.objects.filter(customer_type='customer', is_active=True).first()
            if not customer:
                continue

            user = admin
            if getattr(lead, 'assigned_salesperson', None) and lead.assigned_salesperson.user_id:
                user = lead.assigned_salesperson.user

            estimate = Estimate.objects.create(
                customer=customer,
                assigned_to=user,
                prepared_by=user.get_full_name() or user.username,
                date=today - timedelta(days=days_ago),
                valid_until=today + timedelta(days=45),
                status=status,
                type_of_occupancy=occupancy,
                type_of_work=work_type,
                notes=marker,
                client_note='Demo pipeline estimate for sales forecasting.',
                created_by=admin,
            )
            self._add_estimate_lines(estimate, tax_code, admin, variant=int(seq))
            estimate.calculate_totals()
            created += 1
        return created

    def _enrich_active_projects(self, admin, today: date) -> int:
        from apps.projects.models import Project, ProjectExpense, Task

        enriched = 0
        categories = [
            ('fire', 'project'),
            ('fire', 'amc'),
            ('cctv', 'maintenance'),
            ('gas', 'maintenance'),
            ('fire', 'rectification'),
            ('fire', 'drawing'),
        ]

        active = Project.objects.filter(
            is_active=True,
            status__in=('planning', 'ongoing', 'on_hold'),
        ).exclude(description__contains=SEED_TAG).order_by('pk')

        for idx, project in enumerate(active):
            marker = self._seed_marker(f'ENRICH-{project.pk}')
            if ProjectExpense.objects.filter(description__contains=marker).exists():
                continue

            cat, sub = categories[idx % len(categories)]
            if not project.category:
                project.category = cat
            if not project.sub_category:
                project.sub_category = sub
            project.save(update_fields=['category', 'sub_category', 'updated_at'])

            if idx == 0:
                Task.objects.get_or_create(
                    project=project,
                    name=f'[{SEED_TAG}] Mobilization planning',
                    defaults={
                        'status': 'in_progress',
                        'estimated_hours': Decimal('24'),
                        'created_by': admin,
                    },
                )
            elif idx in (1, 2):
                spend = Decimal(str(8500 + idx * 1200))
                ProjectExpense.objects.create(
                    project=project,
                    category='material' if idx == 1 else 'labor',
                    description=f'{marker} – site materials / labour',
                    expense_date=today - timedelta(days=5),
                    amount=spend,
                    status='approved',
                    posted=True,
                    created_by=admin,
                )
                project.total_expenses = (project.total_expenses or Decimal('0')) + spend
                project.save(update_fields=['total_expenses', 'updated_at'])
                Task.objects.get_or_create(
                    project=project,
                    name=f'[{SEED_TAG}] Site works week 1',
                    defaults={
                        'status': 'completed' if idx == 2 else 'in_progress',
                        'estimated_hours': Decimal('40'),
                        'created_by': admin,
                    },
                )
            else:
                Task.objects.get_or_create(
                    project=project,
                    name=f'[{SEED_TAG}] Awaiting client PO',
                    defaults={
                        'status': 'pending',
                        'estimated_hours': Decimal('8'),
                        'created_by': admin,
                    },
                )
            enriched += 1
        return enriched

    def _add_project_expenses(self, project, admin, actual_cost: int, est_cost: int, expense_date: date):
        from apps.projects.models import ProjectExpense

        material = Decimal(str(int(actual_cost * 0.45)))
        labour = Decimal(str(int(actual_cost * 0.35)))
        travel = Decimal(str(int(actual_cost * 0.12)))
        other = Decimal(str(actual_cost)) - material - labour - travel
        splits = (
            ('material', material, 'Materials & equipment'),
            ('labor', labour, 'Technician labour'),
            ('travel', travel, 'Site travel & mobilization'),
            ('other', other, 'Miscellaneous site costs'),
        )
        for cat, amt, desc in splits:
            if amt <= 0:
                continue
            ProjectExpense.objects.create(
                project=project,
                category=cat,
                description=f'[{SEED_TAG}] {desc}',
                expense_date=expense_date - timedelta(days=7),
                amount=amt,
                status='approved',
                posted=True,
                created_by=admin,
            )

    def _add_estimate_lines(self, estimate, tax_code, admin, *, variant: int):
        from apps.sales.models import EstimateItem

        base = 5000 + (variant * 750)
        lines = [
            ('Materials', base * 2, 'material'),
            ('Technician labour', base, 'labour'),
            ('Travel & mobilization', int(base * 0.3), 'travel'),
            ('Project supervision', int(base * 0.2), 'overhead'),
        ]
        for i, (desc, amount, _kind) in enumerate(lines):
            qty = Decimal('1')
            unit = Decimal(str(amount))
            EstimateItem.objects.create(
                estimate=estimate,
                group_name='Scope of work',
                sort_order=i,
                description=desc,
                quantity=qty,
                unit_price=unit,
                profit_type='percent',
                profit_value=Decimal('22'),
                tax_code=tax_code,
                is_vat_inclusive=False,
            )

    def _tax_code(self):
        from apps.finance.models import TaxCode

        code = TaxCode.objects.filter(is_active=True, rate=Decimal('5.00')).first()
        if code:
            return code
        from django.core.management import call_command

        call_command('seed_tax_codes', verbosity=0)
        return TaxCode.objects.filter(is_active=True, rate=Decimal('5.00')).first()

    def _print_report_counts(self, today: date):
        from apps.crm.models import Customer
        from apps.projects.models import Project
        from apps.reports.services.lead_forecasting import build_lead_forecast_report_context
        from apps.reports.services.project_forecasting import build_forecast_report_context
        from apps.reports.services.sales_forecasting import build_sales_forecast_report_context
        from apps.sales.models import Estimate

        start = today.replace(day=1)
        pf = build_forecast_report_context(
            start_date=start,
            end_date=today,
            status='',
            manager_id='',
            customer_id='',
            force_refresh=True,
        )
        lf = build_lead_forecast_report_context(
            start_date=start,
            end_date=today,
            stage='',
            salesperson='',
            source='',
            force_refresh=True,
        )
        sf = build_sales_forecast_report_context(
            start_date=start,
            end_date=today,
            status='',
            salesperson_id='',
            customer_id='',
            job_type='',
            force_refresh=True,
        )

        self.stdout.write('\nReport-ready counts (current month window):')
        self.stdout.write(f'  Leads in DB: {Customer.objects.filter(customer_type="lead", is_active=True).count()}')
        self.stdout.write(f'  Lead forecast rows: {lf.get("lead_count", 0)}')
        self.stdout.write(f'  Active projects: {Project.objects.filter(is_active=True).exclude(status__in=["draft","cancelled"]).count()}')
        self.stdout.write(f'  Project forecast rows: {pf.get("project_count", 0)}')
        self.stdout.write(f'  Pipeline estimates: {Estimate.objects.filter(is_active=True).exclude(status__in=["quotation_lost","rejected"]).count()}')
        self.stdout.write(f'  Sales forecast rows: {sf.get("estimate_count", 0)}')
        self.stdout.write(f'  Completed projects (learning): {len(sf.get("completed") or [])}')
