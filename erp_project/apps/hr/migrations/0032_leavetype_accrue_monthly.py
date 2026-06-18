from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0031_uae_eosg_gratuity'),
    ]

    operations = [
        migrations.AddField(
            model_name='leavetype',
            name='accrue_monthly',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Spread annual entitlement evenly across 12 months (e.g. 30 days → 2.5 per month). '
                    'Available balance uses accrual as of today, not the selected leave dates.'
                ),
            ),
        ),
    ]
