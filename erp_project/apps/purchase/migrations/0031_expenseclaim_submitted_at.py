from django.db import migrations, models
from django.db.models import F


def backfill_submitted_at(apps, schema_editor):
    ExpenseClaim = apps.get_model('purchase', 'ExpenseClaim')
    ExpenseClaim.objects.filter(
        status__in=('submitted', 'approved', 'rejected', 'paid'),
        submitted_at__isnull=True,
    ).update(submitted_at=F('created_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0030_purchaseorderitem_brand_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='expenseclaim',
            name='submitted_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the claim was submitted for approval.',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_submitted_at, migrations.RunPython.noop),
    ]
