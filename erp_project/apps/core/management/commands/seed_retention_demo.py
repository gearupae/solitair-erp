"""
Seed demo data for retention workflows: quotations, projects (checklist + technicians),
purchase orders, retention invoices, and vendor bills.

Safe to re-run: uses DEMO-RET-* markers and skips existing rows.

Run on production:
  cd /var/www/gearuperp/erp_project && source ../venv/bin/activate
  python manage.py seed_retention_demo
  python manage.py seed_retention_demo --with-base   # also run alnajah + HR demo if needed
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()

SEED_TAG = 'DEMO-RET'
SEED_NOTE = 'Seeded by seed_retention_demo'
AN_TAG = 'DEMO-AN'

CHECKLIST_TEMPLATES = [
    ('Fire alarm control panel inspected and tested', False),
    ('Sprinkler heads pressure-tested on level 1', False),
    ('Emergency exit signage illuminated', False),
    ('Fire hose reel cabinet — seal broken (needs replacement)', True),
    ('Smoke detectors cleaned in plant room', False),
    ('Fire pump room ventilation checked', False),
]

SCENARIOS = [
    {
        'key': 'A',
        'customer': 'Dubai Creek Tower Management',
        'project': 'Fire Protection Fit-out – Creek Tower',
        'category': 'fire',
        'sub_category': 'project',
        'estimate_status': 'quotation_won',
        'sales_retention': Decimal('10'),
        'po_retention': Decimal('10'),
        'contract_value': Decimal('420000'),
        'po_status': 'confirmed',
    },
    {
        'key': 'B',
        'customer': 'Marina Walk Residences HOA',
        'project': 'Annual AMC – Marina Walk',
        'category': 'fire',
        'sub_category': 'amc',
        'estimate_status': 'approved',
        'sales_retention': Decimal('5'),
        'po_retention': Decimal('5'),
        'contract_value': Decimal('96000'),
        'po_status': 'sent',
    },
    {
        'key': 'C',
        'customer': 'Sharjah Industrial Zone Authority',
        'project': 'Sprinkler Upgrade – Block C',
        'category': 'fire',
        'sub_category': 'maintenance',
        'estimate_status': 'quotation_won',
        'sales_retention': Decimal('10'),
        'po_retention': Decimal('5'),
        'contract_value': Decimal('185000'),
        'po_status': 'confirmed',
    },
]

ESTIMATE_LINES = [
    ('Fire detection materials', Decimal('1'), Decimal('45000')),
    ('Suppression equipment supply', Decimal('1'), Decimal('32000')),
    ('Installation & commissioning labour', Decimal('1'), Decimal('28000')),
    ('Testing, certification & handover', Decimal('1'), Decimal('12000')),
]

PO_LINES = [
    ('FD-001', Decimal('40'), Decimal('85')),
    ('FS-001', Decimal('60'), Decimal('28')),
    ('EE-001', Decimal('25'), Decimal('55')),
]

INVOICE_LINES = [
    ('Milestone 1 – mobilization & materials', Decimal('1'), Decimal('55000')),
    ('Milestone 2 – installation progress', Decimal('1'), Decimal('38000')),
]


class Command(BaseCommand):
    help = 'Seed retention demo: quotations, POs, projects, checklists, technicians, retention invoices.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--with-base',
            action='store_true',
            help='Run seed_alnajah_demo and seed_hr_demo first if inventory/HR data is missing',
        )
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Delete existing DEMO-RET demo rows and re-seed with current retention logic',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        today = date.today()
        admin = User.objects.filter(is_superuser=True).first() or User.objects.filter(is_active=True).first()
        if not admin:
            self.stderr.write(self.style.ERROR('No active user found.'))
            return

        if options['refresh']:
            removed = self._clear_demo_retention()
            self.stdout.write(self.style.WARNING(f'Removed {removed} prior DEMO-RET record groups'))

        if options['with_base']:
            self._ensure_base_data()

        tax_code = self._tax_code()
        items = self._inventory_items()
        vendors = list(self._vendors())
        technicians = self._technician_users()

        counts = {'scenarios': 0, 'estimates': 0, 'invoices': 0, 'pos': 0, 'bills': 0, 'checklist': 0}

        for spec in SCENARIOS:
            marker = f'{SEED_TAG}-{spec["key"]}'
            if self._scenario_exists(marker):
                self.stdout.write(f'  Skip {marker} (already seeded)')
                continue

            result = self._seed_scenario(
                spec, marker, admin, today, tax_code, items, vendors, technicians,
            )
            counts['scenarios'] += 1
            for k, v in result.items():
                counts[k] = counts.get(k, 0) + v

        self.stdout.write(self.style.SUCCESS('\nRetention demo seed complete:'))
        for key, val in counts.items():
            self.stdout.write(f'  {key}: {val}')

    def _ensure_base_data(self):
        from apps.inventory.models import Item

        if not Item.objects.filter(is_active=True).exists():
            self.stdout.write('Running seed_alnajah_demo...')
            call_command('seed_alnajah_demo', skip_hr=True, verbosity=1)
        from apps.hr.models import Employee

        if not Employee.objects.filter(employee_code__startswith=AN_TAG).exists():
            self.stdout.write('Running seed_hr_demo...')
            call_command('seed_hr_demo', verbosity=1)
            call_command('sync_employee_users', verbosity=0)

    def _scenario_exists(self, marker: str) -> bool:
        from apps.sales.models import Estimate

        return Estimate.objects.filter(notes__contains=marker).exists()

    def _clear_demo_retention(self) -> int:
        """Remove prior DEMO-RET quotations, projects, invoices, POs, and vendor bills."""
        from apps.projects.models import Project, ProjectInvoice
        from apps.purchase.models import PurchaseOrder, PurchaseRequest, VendorBill
        from apps.sales.models import Estimate, Invoice

        removed = 0
        markers = [f'{SEED_TAG}-{spec["key"]}' for spec in SCENARIOS]

        for marker in markers:
            inv_ids = list(Invoice.objects.filter(notes__contains=marker).values_list('pk', flat=True))
            if inv_ids:
                ProjectInvoice.objects.filter(invoice_id__in=inv_ids).delete()
                Invoice.objects.filter(pk__in=inv_ids).delete()
                removed += 1

            if VendorBill.objects.filter(notes__contains=marker).delete()[0]:
                removed += 1
            if PurchaseOrder.objects.filter(notes__contains=marker).delete()[0]:
                removed += 1
            if PurchaseRequest.objects.filter(notes__contains=marker).delete()[0]:
                removed += 1
            if Estimate.objects.filter(notes__contains=marker).delete()[0]:
                removed += 1
            if Project.objects.filter(description__contains=marker).delete()[0]:
                removed += 1

        from apps.crm.models import Customer

        for marker in markers:
            if Customer.objects.filter(notes__contains=marker).delete()[0]:
                removed += 1

        return removed

    def _seed_scenario(self, spec, marker, admin, today, tax_code, items, vendors, technicians) -> dict:
        from apps.crm.models import Customer
        from apps.projects.models import Project, ProjectChecklistItem, ProjectInvoice, Task
        from apps.purchase.models import (
            PurchaseOrder,
            PurchaseOrderItem,
            PurchaseRequest,
            PurchaseRequestItem,
            Vendor,
            VendorBill,
            VendorBillItem,
        )
        from apps.sales.models import Estimate, Invoice, InvoiceItem
        from apps.sales.project_retention import sync_invoice_retention_links
        from apps.sales.sales_order import ensure_sales_order_number
        from apps.purchase.po_retention import sync_vendor_bill_retention_links

        counts = {'estimates': 0, 'invoices': 0, 'pos': 0, 'bills': 0, 'checklist': 0}

        customer, _ = Customer.objects.get_or_create(
            name=f'[{SEED_TAG}] {spec["customer"]}',
            defaults={
                'email': f'demo.{spec["key"].lower()}@retention.demo',
                'phone': f'+9714{ord(spec["key"]):07d}',
                'company': spec['customer'],
                'address': f'{spec["customer"]}, UAE',
                'city': 'Dubai',
                'country': 'United Arab Emirates',
                'trn': f'100{ord(spec["key"]):012d}'[:15],
                'scope': 'project',
                'job_type': ['fire_protection_system'],
                'business_segment': 'b2b',
                'payment_terms': 'Net 30',
                'credit_limit': Decimal('500000'),
                'status': 'active',
                'customer_type': 'customer',
                'notes': f'{SEED_NOTE} {marker}',
                'created_by': admin,
            },
        )

        start = today - timedelta(days=45)
        end = today + timedelta(days=120)
        project = Project.objects.create(
            name=f'[{SEED_TAG}] {spec["project"]}',
            description=f'{SEED_NOTE} {marker} – demo project with retention, checklist, and technicians.',
            customer=customer,
            manager=admin,
            status='ongoing',
            category=spec['category'],
            sub_category=spec['sub_category'],
            billing_type='fixed',
            budget=spec['contract_value'],
            estimated_cost=spec['contract_value'] * Decimal('0.72'),
            contract_value=spec['contract_value'],
            start_date=start,
            end_date=end,
            created_by=admin,
        )
        project.members.add(admin)
        techs = technicians[:3] if technicians else [admin]
        project.technicians.set(techs)
        project.ensure_checklist_public_token()

        for i, (text, flagged) in enumerate(CHECKLIST_TEMPLATES):
            ProjectChecklistItem.objects.create(
                project=project,
                text=text,
                item_date=today - timedelta(days=max(0, 6 - i)),
                is_flagged_red=flagged,
                sort_order=i,
                created_by=admin,
            )
            counts['checklist'] += 1

        Task.objects.create(
            project=project,
            name=f'[{SEED_TAG}] Site mobilization',
            status='in_progress',
            estimated_hours=Decimal('32'),
            created_by=admin,
        )
        Task.objects.create(
            project=project,
            name=f'[{SEED_TAG}] Fire alarm commissioning',
            status='pending',
            estimated_hours=Decimal('24'),
            created_by=admin,
        )

        estimate = Estimate.objects.create(
            customer=customer,
            project=project,
            assigned_to=admin,
            prepared_by=admin.get_full_name() or admin.username,
            date=start,
            valid_until=today + timedelta(days=60),
            status=spec['estimate_status'],
            retention_percent=spec['sales_retention'],
            type_of_occupancy='commercial',
            type_of_work='installation_with_amc',
            scope_of_work='Fire Detection',
            notes=f'{SEED_NOTE} {marker}',
            client_note='Demo quotation with project retention for testing.',
            created_by=admin,
        )
        self._add_estimate_lines(estimate, tax_code, items)
        estimate.calculate_totals()
        if spec['estimate_status'] == 'quotation_won':
            ensure_sales_order_number(estimate)
        counts['estimates'] += 1

        vendor = vendors[ord(spec['key']) % len(vendors)] if vendors else None
        if vendor:
            pr = PurchaseRequest.objects.create(
                date=today - timedelta(days=10),
                requested_by=admin,
                required_by_date=today + timedelta(days=21),
                priority='high',
                status='approved',
                notes=f'{SEED_NOTE} {marker} PR',
                created_by=admin,
            )
            for code_suffix, qty, price in PO_LINES:
                item = self._item_by_suffix(items, code_suffix)
                PurchaseRequestItem.objects.create(
                    purchase_request=pr,
                    inventory_item=item,
                    description=item.name if item else f'Demo {code_suffix}',
                    quantity=qty,
                    estimated_price=price,
                )
            pr.calculate_total()

            po = PurchaseOrder.objects.create(
                purchase_request=pr,
                vendor=vendor,
                project=project,
                retention_percent=spec['po_retention'],
                order_date=today - timedelta(days=7),
                expected_delivery_date=today + timedelta(days=14),
                status=spec['po_status'],
                notes=f'{SEED_NOTE} {marker} PO',
                terms_and_conditions='Net 30. Retention per contract terms.',
                created_by=admin,
            )
            for code_suffix, qty, price in PO_LINES:
                item = self._item_by_suffix(items, code_suffix)
                PurchaseOrderItem.objects.create(
                    purchase_order=po,
                    inventory_item=item,
                    description=item.name if item else f'Demo {code_suffix}',
                    quantity=qty,
                    unit_price=price,
                    tax_code=tax_code,
                    is_vat_inclusive=False,
                )
            po.calculate_totals()
            counts['pos'] += 1

            bill = VendorBill.objects.create(
                purchase_order=po,
                vendor=vendor,
                project=project,
                vendor_invoice_number=f'VINV-{marker}',
                bill_date=today - timedelta(days=3),
                due_date=today + timedelta(days=27),
                status='draft',
                notes=f'{SEED_NOTE} {marker} vendor bill with retention',
                created_by=admin,
            )
            sync_vendor_bill_retention_links(bill)
            for poi in po.items.all():
                VendorBillItem.objects.create(
                    bill=bill,
                    description=poi.description,
                    quantity=poi.quantity,
                    unit_price=poi.unit_price,
                    tax_code=poi.tax_code,
                    is_vat_inclusive=poi.is_vat_inclusive,
                )
            bill.calculate_totals()
            counts['bills'] += 1

        for idx, (desc, qty, unit) in enumerate(INVOICE_LINES[:2 if spec['key'] == 'B' else 2]):
            inv = Invoice.objects.create(
                estimate=estimate,
                customer=customer,
                project=project,
                invoice_date=today - timedelta(days=14 - idx * 7),
                due_date=today + timedelta(days=16 - idx * 7),
                status='draft',
                notes=f'{SEED_NOTE} {marker} invoice {idx + 1}',
                created_by=admin,
            )
            sync_invoice_retention_links(inv)
            InvoiceItem.objects.create(
                invoice=inv,
                description=desc,
                quantity=qty,
                unit_price=unit,
                tax_code=tax_code,
                is_vat_inclusive=False,
            )
            inv.calculate_totals()
            ProjectInvoice.objects.get_or_create(
                project=project,
                invoice=inv,
                defaults={'description': desc, 'created_by': admin},
            )
            counts['invoices'] += 1

        return counts

    def _add_estimate_lines(self, estimate, tax_code, items):
        from apps.sales.models import EstimateItem

        sort_order = 0
        for desc, qty, unit in ESTIMATE_LINES:
            item = items[sort_order % len(items)] if items else None
            EstimateItem.objects.create(
                estimate=estimate,
                group_name='Scope of work',
                sort_order=sort_order,
                inventory_item=item,
                description=desc,
                quantity=qty,
                unit_price=unit,
                profit_type='percent',
                profit_value=Decimal('20'),
                tax_code=tax_code,
                is_vat_inclusive=False,
            )
            sort_order += 1

    def _item_by_suffix(self, items, code_suffix: str):
        from apps.inventory.models import Item

        prefixed = Item.objects.filter(item_code=f'{AN_TAG}-{code_suffix}', is_active=True).first()
        if prefixed:
            return prefixed
        for item in items:
            if code_suffix in (item.item_code or ''):
                return item
        return items[0] if items else None

    def _inventory_items(self):
        from apps.inventory.models import Item

        qs = Item.objects.filter(is_active=True).order_by('item_code')
        an = list(qs.filter(item_code__startswith=f'{AN_TAG}-')[:10])
        return an or list(qs[:10])

    def _vendors(self):
        from apps.purchase.models import Vendor

        qs = Vendor.objects.filter(is_active=True, status='active')
        tagged = list(qs.filter(name__startswith=f'[{AN_TAG}]')[:4])
        return tagged or list(qs[:4])

    def _technician_users(self):
        from apps.hr.models import Employee

        users = []
        for emp in Employee.objects.filter(
            employee_code__startswith=AN_TAG,
            status='active',
            designation__name__in=('Field Technician', 'Site Supervisor', 'Project Engineer'),
        ).select_related('user')[:6]:
            if emp.user_id and emp.user.is_active:
                users.append(emp.user)
        if not users:
            users = list(
                User.objects.filter(is_active=True, is_staff=True).exclude(is_superuser=True)[:4]
            )
        return users

    def _tax_code(self):
        from apps.finance.models import TaxCode

        code = TaxCode.objects.filter(is_active=True, rate=Decimal('5.00')).first()
        if code:
            return code
        call_command('seed_tax_codes', verbosity=0)
        return TaxCode.objects.filter(is_active=True, rate=Decimal('5.00')).first()
