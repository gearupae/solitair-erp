# Generated manually

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0021_employee_salary_template_payroll_gross_salary'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendancerecord',
            name='overtime_type',
            field=models.CharField(
                choices=[
                    ('normal', 'Normal (daytime)'),
                    ('night', 'Night (22:00–04:00)'),
                    ('holiday', 'Public holiday'),
                ],
                default='normal',
                help_text='Used for payroll OT rate (normal / night / holiday).',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='attendancesettings',
            name='overtime_rate_holiday',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('1.50'),
                help_text='Public holiday OT multiplier.',
                max_digits=8,
            ),
        ),
        migrations.AddField(
            model_name='attendancesettings',
            name='overtime_rate_night',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('1.50'),
                help_text='Night OT (e.g. 22:00–04:00) multiplier.',
                max_digits=8,
            ),
        ),
        migrations.AddField(
            model_name='attendancesettings',
            name='overtime_rate_normal',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('1.25'),
                help_text='Daytime OT multiplier (UAE).',
                max_digits=8,
            ),
        ),
        migrations.AlterField(
            model_name='attendancesettings',
            name='overtime_rate_multiplier',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('1.50'),
                help_text='Legacy single multiplier (non-UAE payroll path only).',
                max_digits=8,
            ),
        ),
    ]
