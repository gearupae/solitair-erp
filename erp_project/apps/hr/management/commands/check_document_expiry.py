"""Cron-friendly: email HR for documents expiring within N days (amber/critical tiers)."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.hr import hr_notifications


def _documents_for_employee(emp):
    """Yield (label, expiry_date) for compliance-related dates."""
    uc = getattr(emp, 'uae_compliance', None)
    kc = getattr(emp, 'ksa_compliance', None)

    if emp.visa_expiry:
        yield ('Visa', emp.visa_expiry)
    if uc:
        if uc.emirates_id_expiry:
            yield ('Emirates ID', uc.emirates_id_expiry)
        if uc.passport_expiry:
            yield ('Passport', uc.passport_expiry)
        if uc.labour_card_expiry:
            yield ('Labour card', uc.labour_card_expiry)
        if uc.medical_insurance_expiry:
            yield ('Medical insurance (UAE)', uc.medical_insurance_expiry)
    if kc:
        if kc.iqama_expiry:
            yield ('Iqama', kc.iqama_expiry)
        if kc.work_permit_expiry:
            yield ('Work permit', kc.work_permit_expiry)
        if kc.passport_expiry:
            yield ('Passport (KSA)', kc.passport_expiry)
        if kc.medical_insurance_expiry:
            yield ('Medical insurance (KSA)', kc.medical_insurance_expiry)


class Command(BaseCommand):
    help = 'Email HR for each document expiring within N days (≤7 critical, 8–30 amber).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--within-days',
            type=int,
            default=30,
            help='Include documents expiring in this many days (default 30)',
        )

    def handle(self, *args, **options):
        horizon = max(0, int(options.get('within_days', 30) or 30))
        today = date.today()
        from apps.hr.models import Employee

        sent = 0
        for emp in Employee.objects.filter(is_active=True):
            for label, exp in _documents_for_employee(emp):
                days_left = (exp - today).days
                if not (0 <= days_left <= horizon):
                    continue
                hr_notifications.send_document_expiry_alert(
                    employee_name=emp.full_name,
                    doc_label=label,
                    expiry_date=exp,
                    days_left=days_left,
                )
                sent += 1

        if sent == 0:
            self.stdout.write('No expiring documents in window.')
            return
        self.stdout.write(self.style.SUCCESS(f'Sent {sent} document expiry alert(s).'))
