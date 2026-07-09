# Generated manually for vendor bill approval workflow

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0031_expenseclaim_submitted_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendorbill',
            name='rejection_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='vendorbill',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('pending_approval', 'Pending Approval'),
                    ('approved', 'Approved'),
                    ('returned', 'Returned for Revision'),
                    ('rejected', 'Rejected'),
                    ('posted', 'Posted'),
                    ('pending', 'Pending'),
                    ('paid', 'Paid'),
                    ('partial', 'Partially Paid'),
                    ('overdue', 'Overdue'),
                ],
                default='draft',
                max_length=20,
            ),
        ),
    ]
