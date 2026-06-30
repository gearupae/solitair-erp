from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0016_customer_job_type_scope_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='crmleadkanbanstage',
            name='is_site_visit',
            field=models.BooleanField(
                default=False,
                help_text='If checked, leads in this column appear on the dashboard Notifications card.',
            ),
        ),
    ]
