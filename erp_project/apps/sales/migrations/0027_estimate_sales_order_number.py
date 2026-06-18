"""Add sales_order_number to won quotations."""
import re

from django.db import migrations, models

_SO_PATTERN = re.compile(r'^SO-(\d+)$', re.IGNORECASE)


def backfill_sales_order_numbers(apps, schema_editor):
    Estimate = apps.get_model('sales', 'Estimate')
    won = list(
        Estimate.objects.filter(status='quotation_won')
        .exclude(sales_order_number__isnull=False)
        .order_by('date', 'pk')
    )
    # Also include rows with empty string
    won += list(
        Estimate.objects.filter(status='quotation_won', sales_order_number='')
        .order_by('date', 'pk')
    )
    seen_pks = set()
    ordered = []
    for est in won:
        if est.pk in seen_pks:
            continue
        seen_pks.add(est.pk)
        ordered.append(est)

    max_seq = 0
    for num in Estimate.objects.exclude(sales_order_number__isnull=True).exclude(
        sales_order_number=''
    ).values_list('sales_order_number', flat=True):
        match = _SO_PATTERN.match((num or '').strip())
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    for est in ordered:
        if (est.sales_order_number or '').strip():
            match = _SO_PATTERN.match(est.sales_order_number.strip())
            if match:
                max_seq = max(max_seq, int(match.group(1)))
            continue
        max_seq += 1
        est.sales_order_number = f'SO-{max_seq}'
        est.save(update_fields=['sales_order_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0026_estimate_revision_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='sales_order_number',
            field=models.CharField(
                blank=True,
                editable=False,
                help_text='Assigned when quotation is won (SO-1, SO-2, …).',
                max_length=50,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill_sales_order_numbers, migrations.RunPython.noop),
    ]
