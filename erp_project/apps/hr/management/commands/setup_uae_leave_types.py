"""
Management command to set up UAE Labor Law compliant leave types.
Run: python manage.py setup_uae_leave_types
"""
from django.core.management.base import BaseCommand
from apps.hr.models import LeaveType


class Command(BaseCommand):
    help = 'Set up UAE Labor Law compliant leave types'

    def handle(self, *args, **options):
        self.stdout.write('Setting up UAE leave types...')
        
        leave_types_data = [
            {
                'name': 'Annual Leave',
                'code': 'ANNUAL',
                'days_allowed': 30,  # UAE: 30 days per year for employees with 1+ year service
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': False,
                'is_paid': True,
                'description': 'Annual leave as per UAE Labor Law - 30 days per year for employees with 1+ year service'
            },
            {
                'name': 'Sick Leave (During Probation)',
                'code': 'SICK_PROBATION',
                'days_allowed': 0,  # Unpaid during probation
                'is_probation_only': True,
                'is_gender_specific': False,
                'requires_medical_certificate': True,
                'is_paid': False,
                'description': 'Sick leave during probation period - unpaid, requires medical certificate'
            },
            {
                'name': 'Sick Leave (Normal)',
                'code': 'SICK_NORMAL',
                'days_allowed': 90,  # UAE: 90 days per year (15 full pay, 30 half pay, 45 unpaid)
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': True,
                'is_paid': True,
                'description': 'Sick leave after probation - 90 days per year (15 full pay, 30 half pay, 45 unpaid)'
            },
            {
                'name': 'Maternity Leave',
                'code': 'MATERNITY',
                'days_allowed': 60,  # UAE: 60 days (45 days full pay, 15 days half pay)
                'is_probation_only': False,
                'is_gender_specific': True,
                'gender_required': 'female',
                'requires_medical_certificate': True,
                'is_paid': True,
                'description': 'Maternity leave - 60 days (45 days full pay, 15 days half pay) - Female employees only'
            },
            {
                'name': 'Paternity Leave',
                'code': 'PATERNITY',
                'days_allowed': 5,  # UAE: 5 days
                'is_probation_only': False,
                'is_gender_specific': True,
                'gender_required': 'male',
                'requires_medical_certificate': False,
                'is_paid': True,
                'description': 'Paternity leave - 5 days - Male employees only'
            },
            {
                'name': 'Compassionate Leave',
                'code': 'COMPASSIONATE',
                'days_allowed': 5,  # UAE: 3-5 days typically
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': False,
                'is_paid': True,
                'description': 'Compassionate leave for death of family member - 3-5 days'
            },
            {
                'name': 'Hajj Leave',
                'code': 'HAJJ',
                'days_allowed': 30,  # UAE: 30 days once in lifetime
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': False,
                'is_paid': False,
                'description': 'Hajj leave - 30 days once in lifetime - unpaid'
            },
            {
                'name': 'Study Leave',
                'code': 'STUDY',
                'days_allowed': 10,  # Company policy may vary
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': False,
                'is_paid': False,
                'description': 'Study leave for exams - typically unpaid'
            },
            {
                'name': 'Emergency Leave',
                'code': 'EMERGENCY',
                'days_allowed': 3,  # Company policy
                'is_probation_only': False,
                'is_gender_specific': False,
                'requires_medical_certificate': False,
                'is_paid': False,
                'description': 'Emergency leave - unpaid, requires approval'
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for lt_data in leave_types_data:
            leave_type, created = LeaveType.objects.update_or_create(
                code=lt_data['code'],
                defaults={
                    'name': lt_data['name'],
                    'days_allowed': lt_data['days_allowed'],
                    'is_probation_only': lt_data['is_probation_only'],
                    'is_gender_specific': lt_data['is_gender_specific'],
                    'gender_required': lt_data.get('gender_required', ''),
                    'requires_medical_certificate': lt_data['requires_medical_certificate'],
                    'is_paid': lt_data['is_paid'],
                    'description': lt_data['description'],
                    'is_active': True
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {leave_type.name}'))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f'  Updated: {leave_type.name}'))
        
        self.stdout.write(self.style.SUCCESS(f'\nCompleted! Created: {created_count}, Updated: {updated_count}'))





