# Generated manually

from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0022_overtime_types_and_rates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payrolltemplate',
            name='basic_salary',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Optional reference amount on the template; employee basic is used when generating payroll.',
                max_digits=12,
            ),
        ),
    ]
