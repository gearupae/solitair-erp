"""Replace Expired with Quotation Won / Quotation Lost; map old expired rows to quotation_lost."""

from django.db import migrations, models


def forwards_expired_to_lost(apps, schema_editor):
    Estimate = apps.get_model('sales', 'Estimate')
    Estimate.objects.filter(status='expired').update(status='quotation_lost')


def backwards_lost_to_expired(apps, schema_editor):
    Estimate = apps.get_model('sales', 'Estimate')
    Estimate.objects.filter(status='quotation_lost').update(status='expired')


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_alter_estimateitem_profit_value_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards_expired_to_lost, backwards_lost_to_expired),
        migrations.AlterField(
            model_name='estimate',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('sent', 'Sent'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                    ('quotation_won', 'Quotation Won'),
                    ('quotation_lost', 'Quotation Lost'),
                ],
                default='draft',
                max_length=20,
            ),
        ),
    ]
