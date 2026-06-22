from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_aicompliancesettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='aimoduleknowledge',
            name='auto_run_enabled',
            field=models.BooleanField(
                default=True,
                help_text='When enabled, compliance AI runs automatically on detail pages for this module.',
            ),
        ),
    ]
