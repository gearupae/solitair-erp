# Manual migration: Quotation → Estimate (preserves rows and FKs)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0019_add_is_fixed_deposit_field'),
        ('sales', '0006_add_tax_code_to_line_items'),
    ]

    operations = [
        migrations.RenameModel(old_name='Quotation', new_name='Estimate'),
        migrations.RenameField(
            model_name='estimate',
            old_name='quotation_number',
            new_name='estimate_number',
        ),
        migrations.RenameModel(old_name='QuotationItem', new_name='EstimateItem'),
        migrations.RenameField(
            model_name='estimateitem',
            old_name='quotation',
            new_name='estimate',
        ),
        migrations.RenameField(
            model_name='invoice',
            old_name='quotation',
            new_name='estimate',
        ),
        migrations.AlterField(
            model_name='estimateitem',
            name='tax_code',
            field=models.ForeignKey(
                blank=True,
                help_text='Tax Code determines VAT rate. No selection = Out of Scope (0%)',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='estimate_items',
                to='finance.taxcode',
            ),
        ),
    ]
