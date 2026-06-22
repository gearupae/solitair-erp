from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0036_employee_commission'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeAllowanceExpense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                (
                    'category',
                    models.CharField(
                        choices=[
                            ('allow_housing', 'Allowance — Housing'),
                            ('allow_transport', 'Allowance — Transport'),
                            ('allow_food', 'Allowance — Food'),
                            ('allow_phone', 'Allowance — Phone'),
                            ('allow_other', 'Allowance — Other'),
                            ('exp_travel', 'Expense — Travel'),
                            ('exp_fuel', 'Expense — Fuel'),
                            ('exp_meals', 'Expense — Meals'),
                            ('exp_accommodation', 'Expense — Accommodation'),
                            ('exp_supplies', 'Expense — Supplies'),
                            ('exp_other', 'Expense — Other'),
                        ],
                        default='allow_other',
                        max_length=30,
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
                ('start_date', models.DateField(blank=True, null=True)),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                (
                    'approved_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='approved_allowance_expenses',
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
                        related_name='allowance_expenses',
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
            name='AllowanceExpenseApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('date', models.DateField()),
                ('notes', models.TextField(blank=True)),
                (
                    'allowance_expense',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='applications',
                        to='hr.employeeallowanceexpense',
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
                    'payroll',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='allowance_expense_applications',
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
                'ordering': ['-date', '-pk'],
            },
        ),
    ]
