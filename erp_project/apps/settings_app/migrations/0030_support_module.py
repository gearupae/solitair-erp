from django.db import migrations, models


MODULE_CHOICES = [
    ('crm', 'CRM'),
    ('sales', 'Sales'),
    ('purchase', 'Purchase'),
    ('inventory', 'Inventory'),
    ('finance', 'Finance'),
    ('projects', 'Projects'),
    ('hr', 'HR'),
    ('documents', 'Documents'),
    ('assets', 'Fixed Assets'),
    ('property', 'Property Management'),
    ('service_request', 'Service Request'),
    ('contracts', 'Contracts'),
    ('support', 'Support'),
    ('fleet', 'Fleet'),
    ('reports', 'Reports'),
    ('settings', 'Settings'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0029_ai_credit_nullable_session'),
    ]

    operations = [
        migrations.AlterField(
            model_name='modulepermission',
            name='module',
            field=models.CharField(choices=MODULE_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name='permission',
            name='module',
            field=models.CharField(choices=MODULE_CHOICES, max_length=50),
        ),
    ]
