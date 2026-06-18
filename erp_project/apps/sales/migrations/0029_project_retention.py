# Generated manually for project retention feature

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0021_project_checklist'),
        ('sales', '0028_estimate_public_quotation_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='retention_percent',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Project retention held back from invoices (5%, 10%, or none).',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='project',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invoices',
                to='projects.project',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='retention_percent',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Retention % applied to this invoice (from linked project/estimate).',
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='retention_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Amount held as retention (deducted from invoice total).',
                max_digits=15,
            ),
        ),
    ]
