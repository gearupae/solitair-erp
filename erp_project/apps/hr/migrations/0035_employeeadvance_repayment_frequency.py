from django.db import migrations, models


def backfill_repayment_schedule(apps, schema_editor):
    EmployeeAdvance = apps.get_model('hr', 'EmployeeAdvance')
    for adv in EmployeeAdvance.objects.all():
        months = adv.repayment_months or 1
        adv.repayment_frequency = 'monthly'
        adv.repayment_period = months
        adv.repayment_interval_months = 1
        adv.save(update_fields=['repayment_frequency', 'repayment_period', 'repayment_interval_months'])


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0034_employee_salary_deduction'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeadvance',
            name='repayment_frequency',
            field=models.CharField(
                choices=[
                    ('monthly', 'Monthly'),
                    ('3_month', 'Every 3 months'),
                    ('6_month', 'Every 6 months'),
                    ('yearly', 'Yearly'),
                    ('one_time', 'One time'),
                    ('other', 'Other'),
                ],
                default='monthly',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='employeeadvance',
            name='repayment_interval_months',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Months between each installment (auto-set from frequency; editable for Other).',
            ),
        ),
        migrations.AddField(
            model_name='employeeadvance',
            name='repayment_period',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Number of installments (e.g. 5 monthly deductions).',
            ),
        ),
        migrations.RunPython(backfill_repayment_schedule, migrations.RunPython.noop),
    ]
