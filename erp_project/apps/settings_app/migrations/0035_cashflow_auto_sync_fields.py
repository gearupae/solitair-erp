from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0003_rentinvoice_securitydeposit'),
        ('settings_app', '0034_cashflowincomeline_estimate'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashflowincomeline',
            name='line_source',
            field=models.CharField(
                choices=[('manual', 'Manual'), ('auto_quotation', 'Quotation'), ('auto_amc', 'AMC renewal')],
                default='manual',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='cashflowincomeline',
            name='sync_suppressed',
            field=models.BooleanField(
                default=False,
                help_text='When set, auto-sync will not recreate this line after the user removes it.',
            ),
        ),
        migrations.AddField(
            model_name='cashflowchequeline',
            name='line_source',
            field=models.CharField(
                choices=[('manual', 'Manual'), ('auto_pdc', 'PDC')],
                default='manual',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='cashflowchequeline',
            name='pdc_cheque',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cashflow_cheque_lines',
                to='property.pdccheque',
            ),
        ),
        migrations.AddField(
            model_name='cashflowchequeline',
            name='sync_suppressed',
            field=models.BooleanField(
                default=False,
                help_text='When set, auto-sync will not recreate this line after the user removes it.',
            ),
        ),
        migrations.AddField(
            model_name='cashflowexpenseline',
            name='line_source',
            field=models.CharField(
                choices=[('manual', 'Manual'), ('auto_vendor_bill', 'Vendor bill')],
                default='manual',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='cashflowexpenseline',
            name='sync_suppressed',
            field=models.BooleanField(
                default=False,
                help_text='When set, auto-sync will not recreate this line after the user removes it.',
            ),
        ),
    ]
