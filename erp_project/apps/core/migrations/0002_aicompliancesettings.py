from django.db import migrations, models


def create_default_settings(apps, schema_editor):
    AiComplianceSettings = apps.get_model('core', 'AiComplianceSettings')
    AiComplianceSettings.objects.get_or_create(pk=1, defaults={'auto_run_enabled': True})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_aimoduleknowledge'),
    ]

    operations = [
        migrations.CreateModel(
            name='AiComplianceSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'auto_run_enabled',
                    models.BooleanField(
                        default=True,
                        help_text='When enabled, compliance AI runs automatically in the background after a detail page loads.',
                    ),
                ),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'AI compliance settings',
                'verbose_name_plural': 'AI compliance settings',
            },
        ),
        migrations.RunPython(create_default_settings, migrations.RunPython.noop),
    ]
