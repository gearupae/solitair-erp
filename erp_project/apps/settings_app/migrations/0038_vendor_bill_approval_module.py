# Generated manually — vendor bill approval configuration module

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0037_actual_count'),
    ]

    operations = [
        migrations.AlterField(
            model_name='approvalconfiguration',
            name='module',
            field=models.CharField(
                choices=[
                    ('purchase_request', 'Purchase Request'),
                    ('inventory_request', 'Consumable / Inventory Request'),
                    ('service_request', 'Service Request'),
                    ('estimate', 'Sales Estimate'),
                    ('project', 'Project'),
                    ('project_conversion', 'Project from estimate (draft)'),
                    ('leave', 'Leave Request'),
                    ('recruitment_request', 'Recruitment Request'),
                    ('vendor_bill', 'Vendor Bill'),
                ],
                max_length=50,
                unique=True,
            ),
        ),
    ]
