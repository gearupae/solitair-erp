"""Seed MES demo: work centers, production order, 3-level BOM, sample parts."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.mes.models import (
    BOMItem,
    ChecklistCompletion,
    ChecklistItem,
    Drawing,
    Machine,
    OperationChecklist,
    Part,
    PartScan,
    ProductionOrder,
    WorkCenter,
)
from apps.mes.services.parts_generation import generate_parts_from_bom
from apps.mes.services.po import release_production_order
from apps.mes.services.routing import ensure_routing_for_order
from apps.mes.services.costing import recalculate_wip
from apps.mes.services.scan import get_next_work_center, process_scan
from apps.mes.utils import get_default_mes_company
from apps.settings_app.models import Company

SEED_TAG = 'MES-DEMO'
# code, name, sequence_order, center_type, is_qc_gate, is_production_step
WORK_CENTERS = [
    ('CUT', 'Cutting', 10, WorkCenter.TYPE_MACHINE, False, True),
    ('EDGE', 'Edge Banding', 20, WorkCenter.TYPE_MACHINE, False, True),
    ('CNC', 'CNC Routing', 30, WorkCenter.TYPE_MACHINE, False, True),
    ('ASSY', 'Assembly', 40, WorkCenter.TYPE_MANUAL, False, True),
    ('UPH', 'Upholstery', 50, WorkCenter.TYPE_MANUAL, False, True),
    ('METAL', 'Metal', 60, WorkCenter.TYPE_MACHINE, False, True),
    ('PAINT', 'Paint', 70, WorkCenter.TYPE_MACHINE, False, True),
    ('QC', 'QA / QC', 80, WorkCenter.TYPE_MANUAL, True, True),
    ('DISP', 'Dispatch', 90, WorkCenter.TYPE_LOCATION, False, True),
    ('SAMPLE', 'Material Sample Room', 910, WorkCenter.TYPE_LOCATION, False, False),
    ('STORE', 'Temporary / Future Storage', 920, WorkCenter.TYPE_LOCATION, False, False),
    ('RECYCLE', 'Waste Paint Recycle', 930, WorkCenter.TYPE_LOCATION, False, False),
]

# code → (cost_per_hour AED, capacity units/hr)
WORK_CENTER_RATES = {
    'CUT': (Decimal('85.00'), Decimal('6')),
    'EDGE': (Decimal('75.00'), Decimal('8')),
    'CNC': (Decimal('120.00'), Decimal('4')),
    'ASSY': (Decimal('65.00'), Decimal('5')),
    'UPH': (Decimal('70.00'), Decimal('3')),
    'METAL': (Decimal('95.00'), Decimal('4')),
    'PAINT': (Decimal('80.00'), Decimal('5')),
    'QC': (Decimal('55.00'), Decimal('10')),
    'DISP': (Decimal('45.00'), Decimal('20')),
    'SAMPLE': (Decimal('40.00'), Decimal('10')),
    'STORE': (Decimal('25.00'), Decimal('50')),
    'RECYCLE': (Decimal('30.00'), Decimal('10')),
}

BOM_UNIT_COSTS = {
    'MDF-WAL': Decimal('45.00'),
    'EDGE-WAL': Decimal('8.50'),
    'VNR-OAK': Decimal('120.00'),
    'HW-RUN': Decimal('35.00'),
}


class Command(BaseCommand):
    help = (
        'Seed MES demo data: work centers, one production order with a 3-level BOM, '
        'machines, checklists, and clickable demo parts at Cutting.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh',
            action='store_true',
            help='Remove existing MES-DEMO tagged rows and re-seed.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        company = get_default_mes_company()
        if not company:
            company, _ = Company.objects.get_or_create(
                name='Gearup Manufacturing',
                defaults={'country': 'uae', 'base_currency': 'AED'},
            )
            self.stdout.write(self.style.WARNING(f'Created default company: {company.name}'))

        admin = User.objects.filter(is_superuser=True).order_by('pk').first()

        if options['fresh']:
            self._purge_demo(company)

        if ProductionOrder.objects.filter(company=company, reference=SEED_TAG).exists():
            self.stdout.write(self.style.WARNING('MES demo already seeded. Use --fresh to rebuild.'))
            return

        centers = self._seed_work_centers(company, admin)
        machines = self._seed_machines(company, centers, admin)
        self._seed_checklists(company, centers, admin)

        po = ProductionOrder.objects.create(
            company=company,
            po_number='MES-2026-0001',
            reference=SEED_TAG,
            quantity=2,
            due_date=date.today() + timedelta(days=21),
            status=ProductionOrder.STATUS_DRAFT,
            wip_value=Decimal('0.00'),
            created_by=admin,
            updated_by=admin,
        )

        bom = self._seed_bom(company, po, admin)
        self._seed_drawings(company, bom, admin)
        ensure_routing_for_order(po)
        generated = generate_parts_from_bom(po)
        release_production_order(po)
        recalculate_wip(po)
        parts = list(po.parts.filter(is_active=True).select_related('bom_item', 'current_work_center'))

        self.stdout.write(self.style.SUCCESS('MES demo seeded successfully.'))
        self.stdout.write(f'  Company: {company.name}')
        self.stdout.write(f'  Work centers: {len(centers)}')
        self.stdout.write(f'  Machines: {len(machines)}')
        self.stdout.write(f'  Production order: {po.po_number} (id={po.pk})')
        self.stdout.write(f'  BOM items: {po.bom_items.count()} (3 levels)')
        self.stdout.write(f'  Generated parts: {generated}')
        self.stdout.write('  Demo parts (scan on floor tablet):')
        for part in parts:
            self.stdout.write(f'    - {part.barcode} → {part.bom_item.part_name} @ {part.current_work_center.code}')

        next_wc = get_next_work_center(company, centers['CUT'])
        if not next_wc or next_wc.code != 'EDGE':
            self.stdout.write(self.style.ERROR(
                f'  Routing check FAILED: CUT → {next_wc.code if next_wc else "None"} (expected EDGE)',
            ))
        else:
            self.stdout.write(self.style.SUCCESS('  Routing check: CUT → EDGE ✓'))
            demo_part = parts[0]
            result = process_scan(
                company=company,
                barcode=demo_part.barcode,
                work_center_id=centers['CUT'].pk,
                scan_type='out',
                operator=admin,
            )
            demo_part.refresh_from_db()
            if demo_part.current_work_center.code == 'EDGE':
                self.stdout.write(self.style.SUCCESS(
                    f'  Scan OUT test: {demo_part.barcode} now at {demo_part.current_work_center.code} ✓',
                ))
                demo_part.current_work_center = centers['CUT']
                demo_part.status = Part.STATUS_PENDING
                demo_part.save(update_fields=['current_work_center', 'status', 'updated_at'])
            else:
                self.stdout.write(self.style.ERROR(
                    f'  Scan OUT test FAILED: part at {demo_part.current_work_center.code}',
                ))

    def _purge_demo(self, company):
        demo_pos = ProductionOrder.objects.filter(company=company, reference=SEED_TAG)
        demo_part_ids = list(
            Part.objects.filter(production_order__in=demo_pos).values_list('pk', flat=True),
        )
        PartScan.objects.filter(part_id__in=demo_part_ids).delete()
        ChecklistCompletion.objects.filter(part_id__in=demo_part_ids).delete()
        Part.objects.filter(pk__in=demo_part_ids).delete()
        demo_pos.delete()
        self.stdout.write('Removed previous MES-DEMO production data (work centers preserved).')

    def _seed_work_centers(self, company, admin):
        centers = {}
        for code, name, seq, ctype, qc, is_line in WORK_CENTERS:
            wc, created = WorkCenter.objects.get_or_create(
                company=company,
                code=code,
                defaults={
                    'name': name,
                    'sequence_order': seq,
                    'center_type': ctype,
                    'is_qc_gate': qc,
                    'is_production_step': is_line,
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            if not created:
                wc.name = name
                wc.sequence_order = seq
                wc.center_type = ctype
                wc.is_qc_gate = qc
                wc.is_production_step = is_line
                wc.is_active = True
                wc.updated_by = admin
            rates = WORK_CENTER_RATES.get(code, (Decimal('50.00'), Decimal('5')))
            wc.cost_per_hour = rates[0]
            wc.capacity_units_per_hour = rates[1]
            if not created:
                wc.save(update_fields=[
                    'name', 'sequence_order', 'center_type', 'is_qc_gate',
                    'is_production_step', 'is_active', 'updated_by', 'updated_at',
                    'cost_per_hour', 'capacity_units_per_hour',
                ])
            elif created:
                wc.cost_per_hour = rates[0]
                wc.capacity_units_per_hour = rates[1]
                wc.save(update_fields=['cost_per_hour', 'capacity_units_per_hour', 'updated_at'])
            centers[code] = wc
        return centers

    def _seed_machines(self, company, centers, admin):
        specs = [
            ('Panel Saw', 'CUT', Machine.PROTOCOL_OPCUA, 'opc.tcp://sim-cut:4840'),
            ('Edge Bander #1', 'EDGE', Machine.PROTOCOL_MODBUS, 'modbus://sim-edge:502'),
            ('CNC Router', 'CNC', Machine.PROTOCOL_OPCUA, 'opc.tcp://sim-cnc:4840'),
            ('Spray Booth', 'PAINT', Machine.PROTOCOL_MQTT, 'mqtt://sim-paint:1883'),
        ]
        machines = []
        for name, wc_code, protocol, endpoint in specs:
            machine, _ = Machine.objects.get_or_create(
                company=company,
                name=name,
                work_center=centers[wc_code],
                defaults={
                    'protocol': protocol,
                    'plc_endpoint': endpoint,
                    'is_online': True,
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            machines.append(machine)
        return machines

    def _seed_checklists(self, company, centers, admin):
        for wc_code in ('CUT', 'EDGE', 'CNC', 'QC'):
            wc = centers[wc_code]
            checklist, _ = OperationChecklist.objects.get_or_create(
                company=company,
                work_center=wc,
                name=f'{wc.name} standard checklist',
                defaults={'created_by': admin, 'updated_by': admin},
            )
            labels = {
                'CUT': ['Verify panel grain direction', 'Confirm dimensions vs drawing', 'Deburr edges'],
                'EDGE': ['Match edge tape colour to sample', 'Check adhesion on test strip'],
                'CNC': ['Load correct program', 'Probe zero point', 'First-off inspection'],
                'QC': ['Visual finish check', 'Hardware fit check', 'Packaging readiness'],
            }
            for idx, label in enumerate(labels[wc_code], start=1):
                ChecklistItem.objects.get_or_create(
                    company=company,
                    checklist=checklist,
                    label=label,
                    defaults={
                        'sort_order': idx,
                        'requires_sign_off': True,
                        'created_by': admin,
                        'updated_by': admin,
                    },
                )

    def _seed_bom(self, company, po, admin):
        """3-level BOM: joinery carcass → panels → raw materials."""
        root = BOMItem.objects.create(
            company=company,
            production_order=po,
            part_name='Executive desk carcass',
            material_type=BOMItem.MATERIAL_PANEL,
            quantity=Decimal('1'),
            unit='set',
            item_code=f'{SEED_TAG}-DESK-ROOT',
            created_by=admin,
            updated_by=admin,
        )
        side_panel = BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=root,
            part_name='Side panel (pair)',
            material_type=BOMItem.MATERIAL_PANEL,
            quantity=Decimal('2'),
            unit='pcs',
            item_code=f'{SEED_TAG}-SIDE',
            created_by=admin,
            updated_by=admin,
        )
        top_panel = BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=root,
            part_name='Desktop panel',
            material_type=BOMItem.MATERIAL_PANEL,
            quantity=Decimal('1'),
            unit='pcs',
            item_code=f'{SEED_TAG}-TOP',
            created_by=admin,
            updated_by=admin,
        )
        BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=side_panel,
            part_name='MDF panel 18mm walnut',
            material_type=BOMItem.MATERIAL_PANEL,
            quantity=Decimal('2.4'),
            unit='sqm',
            item_code=f'{SEED_TAG}-MDF-WAL',
            unit_cost=BOM_UNIT_COSTS['MDF-WAL'],
            created_by=admin,
            updated_by=admin,
        )
        BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=side_panel,
            part_name='PVC edge tape 2mm walnut',
            material_type=BOMItem.MATERIAL_EDGE_TAPE,
            quantity=Decimal('6'),
            unit='m',
            item_code=f'{SEED_TAG}-EDGE-WAL',
            unit_cost=BOM_UNIT_COSTS['EDGE-WAL'],
            created_by=admin,
            updated_by=admin,
        )
        BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=top_panel,
            part_name='Oak veneer sheet A-grade',
            material_type=BOMItem.MATERIAL_VENEER,
            quantity=Decimal('1.8'),
            unit='sqm',
            item_code=f'{SEED_TAG}-VNR-OAK',
            unit_cost=BOM_UNIT_COSTS['VNR-OAK'],
            created_by=admin,
            updated_by=admin,
        )
        BOMItem.objects.create(
            company=company,
            production_order=po,
            parent=root,
            part_name='Soft-close drawer runners',
            material_type=BOMItem.MATERIAL_HARDWARE,
            quantity=Decimal('3'),
            unit='pcs',
            item_code=f'{SEED_TAG}-HW-RUN',
            unit_cost=BOM_UNIT_COSTS['HW-RUN'],
            created_by=admin,
            updated_by=admin,
        )
        return {
            'root': root,
            'side_panel': side_panel,
            'top_panel': top_panel,
        }

    def _seed_drawings(self, company, bom, admin):
        """Released SVG drawings for floor tablet demo."""
        from django.core.files.base import ContentFile

        specs = [
            (bom['side_panel'], 'side-panel-cut.svg', 'Side panel — cutting drawing'),
            (bom['top_panel'], 'desktop-panel-cut.svg', 'Desktop panel — cutting drawing'),
        ]
        for bom_item, filename, title in specs:
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240">'
                f'<rect width="400" height="240" fill="#f8f9fa" stroke="#333"/>'
                f'<text x="20" y="40" font-size="18" font-family="sans-serif">{title}</text>'
                f'<text x="20" y="70" font-size="14" fill="#666">{bom_item.part_name}</text>'
                f'<rect x="40" y="100" width="320" height="100" fill="#dee2e6" stroke="#495057" stroke-width="2"/>'
                f'</svg>'
            )
            drawing, created = Drawing.objects.get_or_create(
                company=company,
                bom_item=bom_item,
                version='1.0',
                defaults={
                    'is_released': True,
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            if created or not drawing.file:
                drawing.file.save(filename, ContentFile(svg.encode('utf-8')), save=True)
                drawing.is_released = True
                drawing.save(update_fields=['is_released', 'updated_at'])
