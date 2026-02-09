# Generated migration for Bank Statement and Bank Reconciliation updates

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_add_budget_banktransfer_reconciliation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create BankStatement model
        migrations.CreateModel(
            name='BankStatement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('statement_number', models.CharField(editable=False, max_length=50, unique=True)),
                ('statement_start_date', models.DateField()),
                ('statement_end_date', models.DateField()),
                ('opening_balance', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('closing_balance', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('total_debits', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('total_credits', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('in_progress', 'In Progress'), ('reconciled', 'Reconciled'), ('locked', 'Locked')], default='draft', max_length=20)),
                ('reconciled_date', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('bank_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='statements', to='finance.bankaccount')),
                ('reconciled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reconciled_statements', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-statement_end_date'],
                'unique_together': {('bank_account', 'statement_start_date', 'statement_end_date')},
            },
        ),
        
        # Create BankStatementLine model
        migrations.CreateModel(
            name='BankStatementLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('line_number', models.PositiveIntegerField(default=0)),
                ('transaction_date', models.DateField()),
                ('value_date', models.DateField(blank=True, null=True)),
                ('description', models.CharField(max_length=500)),
                ('reference', models.CharField(blank=True, max_length=200)),
                ('debit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('credit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('balance', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15)),
                ('reconciliation_status', models.CharField(choices=[('unmatched', 'Unmatched'), ('matched', 'Matched'), ('adjusted', 'Adjusted')], default='unmatched', max_length=20)),
                ('match_method', models.CharField(blank=True, choices=[('auto', 'Auto'), ('manual', 'Manual')], max_length=20)),
                ('matched_record_type', models.CharField(blank=True, choices=[('payment', 'Payment'), ('journal', 'Journal Entry'), ('adjustment', 'Adjustment')], max_length=20)),
                ('matched_date', models.DateTimeField(blank=True, null=True)),
                ('statement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='finance.bankstatement')),
                ('matched_payment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='statement_lines', to='finance.payment')),
                ('matched_journal_line', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='statement_lines', to='finance.journalentryline')),
                ('adjustment_journal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='adjustment_statement_lines', to='finance.journalentry')),
                ('matched_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matched_statement_lines', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['line_number', 'transaction_date'],
                'unique_together': {('statement', 'line_number')},
            },
        ),
        
        # Update BankReconciliation model - add new fields
        migrations.AddField(
            model_name='bankreconciliation',
            name='reconciliation_number',
            field=models.CharField(default='', editable=False, max_length=50, unique=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='bankreconciliation',
            name='bank_statement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reconciliation_summary', to='finance.bankstatement'),
        ),
        migrations.AddField(
            model_name='bankreconciliation',
            name='statement_opening_balance',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15),
        ),
        migrations.AddField(
            model_name='bankreconciliation',
            name='gl_opening_balance',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=15),
        ),
        migrations.AddField(
            model_name='bankreconciliation',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_reconciliations', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='bankreconciliation',
            name='approved_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        
        # Rename fields in BankReconciliation
        migrations.RenameField(
            model_name='bankreconciliation',
            old_name='statement_balance',
            new_name='statement_closing_balance',
        ),
        migrations.RenameField(
            model_name='bankreconciliation',
            old_name='gl_balance',
            new_name='gl_closing_balance',
        ),
        migrations.RenameField(
            model_name='bankreconciliation',
            old_name='other_adjustments',
            new_name='adjustments',
        ),
        
        # Update status choices for BankReconciliation
        migrations.AlterField(
            model_name='bankreconciliation',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('approved', 'Approved')], default='draft', max_length=20),
        ),
        
        # Update ReconciliationItem - add new fields
        migrations.AddField(
            model_name='reconciliationitem',
            name='is_cleared',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='reconciliationitem',
            name='cleared_date',
            field=models.DateField(blank=True, null=True),
        ),
        
        # Update ReconciliationItem choices
        migrations.AlterField(
            model_name='reconciliationitem',
            name='item_type',
            field=models.CharField(choices=[('outstanding_deposit', 'Outstanding Deposit'), ('outstanding_check', 'Outstanding Check'), ('bank_charge', 'Bank Charge'), ('bank_interest', 'Bank Interest'), ('fx_difference', 'FX Difference'), ('other', 'Other')], max_length=30),
        ),
        
        # Rename is_reconciled to is_cleared in ReconciliationItem (keeping both)
        migrations.RemoveField(
            model_name='reconciliationitem',
            name='is_reconciled',
        ),
    ]





