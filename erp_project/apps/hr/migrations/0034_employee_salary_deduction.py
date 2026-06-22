from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0033_employeeattachment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeSalaryDeduction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                (
                    'category',
                    models.CharField(
                        choices=[
                            ('fine', 'Fine'),
                            ('penalty', 'Penalty'),
                            ('damage', 'Damage / loss'),
                            ('other', 'Other'),
                        ],
                        default='fine',
                        max_length=20,
                    ),
                ),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('description', models.TextField(blank=True)),
                (
                    'payment_frequency',
                    models.CharField(
                        choices=[('monthly', 'Monthly'), ('one_time', 'One-time')],
                        default='monthly',
                        max_length=20,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('active', 'Active'),
                            ('cancelled', 'Cancelled'),
                            ('completed', 'Completed'),
                        ],
                        default='active',
                        max_length=20,
                    ),
                ),
                ('effective_from', models.DateField(blank=True, null=True)),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                (
                    'approved_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='approved_salary_deductions',
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
                        related_name='salary_deductions',
                        to='hr.employee',
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
                'ordering': ['-created_at', '-pk'],
            },
        ),
        migrations.CreateModel(
            name='SalaryDeductionApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('date', models.DateField()),
                ('notes', models.TextField(blank=True)),
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
                    'payroll',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='salary_deduction_applications',
                        to='hr.payroll',
                    ),
                ),
                (
                    'salary_deduction',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='applications',
                        to='hr.employeesalarydeduction',
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
                'ordering': ['-date', '-pk'],
            },
        ),
    ]
