from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0020_estimate_text_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='estimate_default_authorized_signature',
            field=models.ImageField(
                blank=True,
                help_text='Default authorized signatory image for new estimates.',
                null=True,
                upload_to='company/estimate_signatures/',
            ),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='estimate_default_customer_signature',
            field=models.ImageField(
                blank=True,
                help_text='Default customer signature image for new estimates.',
                null=True,
                upload_to='company/estimate_signatures/',
            ),
        ),
    ]
