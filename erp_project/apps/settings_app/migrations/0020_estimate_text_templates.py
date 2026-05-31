from django.db import migrations, models


def migrate_legacy_estimate_defaults(apps, schema_editor):
    CompanySettings = apps.get_model('settings_app', 'CompanySettings')
    EstimateTextTemplate = apps.get_model('settings_app', 'EstimateTextTemplate')

    cs = CompanySettings.objects.filter(pk=1).first()
    if not cs:
        return

    if (cs.estimate_default_client_note or '').strip():
        EstimateTextTemplate.objects.create(
            template_type='client_note',
            name='Default',
            body=cs.estimate_default_client_note,
            is_default=True,
            sort_order=0,
            is_active=True,
        )
    if (cs.estimate_default_terms or '').strip():
        EstimateTextTemplate.objects.create(
            template_type='terms',
            name='Default',
            body=cs.estimate_default_terms,
            is_default=True,
            sort_order=0,
            is_active=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0019_functional_manager_roles'),
    ]

    operations = [
        migrations.CreateModel(
            name='EstimateTextTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('template_type', models.CharField(choices=[('client_note', 'Client note'), ('terms', 'Terms & conditions')], max_length=20)),
                ('name', models.CharField(max_length=120)),
                ('body', models.TextField(blank=True)),
                ('is_default', models.BooleanField(default=False, help_text='Pre-selected when creating a new estimate (one default per type).')),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Estimate text template',
                'verbose_name_plural': 'Estimate text templates',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.RunPython(migrate_legacy_estimate_defaults, migrations.RunPython.noop),
    ]
