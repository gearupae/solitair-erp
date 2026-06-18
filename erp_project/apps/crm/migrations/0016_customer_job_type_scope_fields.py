"""Job type → multi JSON; scope → single-choice service scope."""
from django.db import migrations, models

OLD_JOB_TO_SCOPE = {
    'amc': 'amc',
    'project': 'project',
    'maintenance': 'maintenance',
    'direct_sale': 'materials_trading',
}


def migrate_customer_scope_and_job_type(apps, schema_editor):
    Customer = apps.get_model('crm', 'Customer')
    for customer in Customer.objects.all():
        old_scope = customer.legacy_disciplines
        old_job = (customer.legacy_job_type or '').strip()
        new_scope = (customer.service_scope or '').strip()

        if not new_scope and old_job:
            new_scope = OLD_JOB_TO_SCOPE.get(old_job, '')

        customer.service_scope = new_scope
        customer.job_type = []
        customer.save(update_fields=['service_scope', 'job_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0015_customer_name_optional'),
    ]

    operations = [
        migrations.RenameField(
            model_name='customer',
            old_name='scope',
            new_name='legacy_disciplines',
        ),
        migrations.RenameField(
            model_name='customer',
            old_name='job_type',
            new_name='legacy_job_type',
        ),
        migrations.AddField(
            model_name='customer',
            name='service_scope',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', '—'),
                    ('maintenance', 'Maintenance'),
                    ('maintenance_with_amc', 'Maintenance with AMC'),
                    ('amc', 'AMC'),
                    ('project', 'Project'),
                    ('materials_trading', 'Materials Trading'),
                    ('refilling_servicing', 'Refilling & Servicing'),
                    ('decor_work', 'Decor Work'),
                    ('decor_with_amc', 'Decor with AMC'),
                    ('drawing_approvals', 'Drawing Approvals'),
                    ('rectification', 'Rectification'),
                ],
                default='',
                max_length=40,
                verbose_name='Scope',
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='job_type',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='System types: Fire Protection, Gas Protection, CCTV, Smoke Management.',
                verbose_name='Job type',
            ),
        ),
        migrations.RunPython(migrate_customer_scope_and_job_type, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='customer',
            name='legacy_disciplines',
        ),
        migrations.RemoveField(
            model_name='customer',
            name='legacy_job_type',
        ),
        migrations.RenameField(
            model_name='customer',
            old_name='service_scope',
            new_name='scope',
        ),
    ]
