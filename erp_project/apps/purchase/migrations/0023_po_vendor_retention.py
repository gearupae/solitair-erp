# Purchase-order / vendor-bill retention (separate from sales retention)

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0021_project_checklist'),
        ('purchase', '0022_expense_claim_public_submission'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorder',
            name='project',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional project link for retention and vendor bill allocation.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='purchase_orders',
                to='projects.project',
            ),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='retention_percent',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Vendor retention held from bills against this PO (5%, 10%, or none).',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='vendorbill',
            name='retention_percent',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Retention % applied to this vendor bill (from PO or project PO).',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='vendorbill',
            name='retention_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Amount withheld as retention (deducted from AP payable total).',
                max_digits=15,
            ),
        ),
    ]
