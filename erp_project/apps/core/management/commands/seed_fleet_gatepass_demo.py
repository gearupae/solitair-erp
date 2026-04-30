"""
Seed demo fleet vehicles (with other documents) and project gate passes.
Safe to re-run: skips rows that already exist (by plate or SEED-* reference).

Run on production after deploy:
  cd /var/www/gearuperp/erp_project && source ../venv/bin/activate && python manage.py seed_fleet_gatepass_demo
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed demo fleet vehicles and gate passes for dashboards / testing'

    def handle(self, *args, **options):
        today = date.today()
        with transaction.atomic():
            n_fleet = self._seed_fleet(today)
            n_gp = self._seed_gatepasses(today)
        self.stdout.write(self.style.SUCCESS(f'Done. Fleet rows created: {n_fleet}, gate passes created: {n_gp}'))

    def _seed_fleet(self, today: date) -> int:
        from apps.fleet.models import Vehicle, VehicleOtherDocument

        created = 0
        specs = [
            {
                'plate': 'DEMO-F-001',
                'make': 'Toyota',
                'model': 'Hiace',
                'mulkiya': today + timedelta(days=8),
                'insurance': today + timedelta(days=120),
                'docs': [('Annual road permit', today + timedelta(days=5))],
            },
            {
                'plate': 'DEMO-F-002',
                'make': 'Ford',
                'model': 'Ranger',
                'mulkiya': today - timedelta(days=3),
                'insurance': today + timedelta(days=60),
                'docs': [('Salik tag registration', today + timedelta(days=15))],
            },
            {
                'plate': 'DEMO-F-003',
                'make': 'Mercedes',
                'model': 'Sprinter',
                'mulkiya': today + timedelta(days=180),
                'insurance': today + timedelta(days=90),
                'docs': [('RTA clearance', today + timedelta(days=2))],
            },
            {
                'plate': 'DEMO-F-004',
                'make': 'Isuzu',
                'model': 'NPR',
                'mulkiya': today + timedelta(days=30),
                'insurance': today,
                'docs': [],
            },
        ]

        driver = User.objects.filter(is_active=True).order_by('pk').first()

        for spec in specs:
            v, was_created = Vehicle.objects.get_or_create(
                plate_number=spec['plate'],
                defaults={
                    'make': spec['make'],
                    'model': spec['model'],
                    'driver': driver,
                    'mulkiya_expiry': spec['mulkiya'],
                    'insurance_expiry': spec['insurance'],
                },
            )
            if was_created:
                created += 1
                for doc_name, exp in spec['docs']:
                    VehicleOtherDocument.objects.get_or_create(
                        vehicle=v,
                        document_name=doc_name,
                        defaults={'expiry_date': exp},
                    )
        return created

    def _seed_gatepasses(self, today: date) -> int:
        from apps.projects.models import Project, ProjectGatepass

        proj = Project.objects.filter(is_active=True).order_by('pk').first()
        if not proj:
            self.stdout.write(self.style.WARNING('No active project found — skipped gate passes'))
            return 0

        members = list(proj.members.filter(is_active=True)[:3])
        if len(members) < 1:
            candidates = list(User.objects.filter(is_active=True).order_by('pk')[:2])
            for u in candidates:
                proj.members.add(u)
            members = list(proj.members.all()[:3])

        if not members:
            self.stdout.write(self.style.WARNING('No users available for gate pass members — skipped'))
            return 0

        specs = [
            {
                'ref': 'SEED-GP-001',
                'member': members[0],
                'start': today - timedelta(days=20),
                'expiry': today + timedelta(days=7),
            },
            {
                'ref': 'SEED-GP-002',
                'member': members[min(1, len(members) - 1)],
                'start': today - timedelta(days=5),
                'expiry': today,
            },
            {
                'ref': 'SEED-GP-003',
                'member': members[0],
                'start': today - timedelta(days=60),
                'expiry': today - timedelta(days=2),
            },
        ]

        created = 0
        for spec in specs:
            _, was_created = ProjectGatepass.objects.get_or_create(
                project=proj,
                reference_number=spec['ref'],
                defaults={
                    'member': spec['member'],
                    'start_date': spec['start'],
                    'expiry_date': spec['expiry'],
                    'notes': 'Seeded by seed_fleet_gatepass_demo',
                },
            )
            if was_created:
                created += 1
        return created
