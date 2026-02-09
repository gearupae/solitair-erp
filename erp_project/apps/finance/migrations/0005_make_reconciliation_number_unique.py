# Generated migration to make reconciliation_number unique

from django.db import migrations, models
from apps.core.utils import generate_number


def populate_reconciliation_numbers(apps, schema_editor):
    """Populate reconciliation_number for existing records."""
    BankReconciliation = apps.get_model('finance', 'BankReconciliation')
    for idx, recon in enumerate(BankReconciliation.objects.all(), start=1):
        if not recon.reconciliation_number:
            recon.reconciliation_number = f"RECON-{recon.reconciliation_date.year}-{str(idx).zfill(4)}"
            recon.save(update_fields=['reconciliation_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0004_bankstatement_bankstatementline_update_reconciliation'),
    ]

    operations = [
        # First populate existing records
        migrations.RunPython(populate_reconciliation_numbers, reverse_code=migrations.RunPython.noop),
        
        # Then make the field unique
        migrations.AlterField(
            model_name='bankreconciliation',
            name='reconciliation_number',
            field=models.CharField(editable=False, max_length=50, unique=True),
        ),
    ]





