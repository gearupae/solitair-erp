# Generated manually for purchase order approval workflow

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0034_purchaseorder_currency'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaseorder',
            name='rejection_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='purchaseorder',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('pending_approval', 'Pending Approval'),
                    ('returned', 'Returned for Revision'),
                    ('rejected', 'Rejected'),
                    ('sent', 'Sent'),
                    ('confirmed', 'Confirmed'),
                    ('partial_received', 'Partially Received'),
                    ('received', 'Received'),
                    ('cancelled', 'Cancelled'),
                ],
                default='draft',
                max_length=20,
            ),
        ),
    ]
