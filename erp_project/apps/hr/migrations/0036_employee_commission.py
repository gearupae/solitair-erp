from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0035_employeeadvance_repayment_frequency'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='employeehrprofile',
            name='commission_fixed_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Used when commission type is Fixed (flat monthly commission when sales exist).',
                max_digits=15,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='employeehrprofile',
            name='commission_percentage',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Used when commission type is Percentage (e.g. 5.00 = 5% of monthly sales).',
                max_digits=6,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='employeehrprofile',
            name='commission_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'None'),
                    ('percentage', 'Percentage of sales'),
                    ('fixed', 'Fixed amount'),
                ],
                default='',
                help_text='How payroll commissions are calculated for this employee.',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='EmployeeCommission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('month', models.DateField(help_text='First day of the commission month.')),
                ('total_sales', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('commission_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('active', 'Active'),
                            ('paid', 'Paid via payroll'),
                            ('cancelled', 'Cancelled'),
                        ],
                        default='active',
                        max_length=20,
                    ),
                ),
                ('notes', models.TextField(blank=True)),
                (
                    'approved_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='approved_employee_commissions',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_created',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'employee',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='commissions',
                        to='hr.employee',
                    ),
                ),
                (
                    'payroll',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='employee_commissions',
                        to='hr.payroll',
                    ),
                ),
                (
                    'updated_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_updated',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['-month', '-pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='employeecommission',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_active', True)),
                fields=('employee', 'month'),
                name='hr_employeecommission_unique_active_employee_month',
            ),
        ),
    ]
