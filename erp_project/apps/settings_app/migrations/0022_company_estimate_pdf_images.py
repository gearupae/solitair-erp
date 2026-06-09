from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0021_company_estimate_default_signatures'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='estimate_pdf_stamp_image',
            field=models.ImageField(
                blank=True,
                help_text='Company stamp or seal shown on estimate quotation PDFs.',
                null=True,
                upload_to='company/estimate_pdf/',
            ),
        ),
        migrations.AddField(
            model_name='companysettings',
            name='estimate_pdf_footer_image',
            field=models.ImageField(
                blank=True,
                help_text='Optional footer banner or certification image on estimate PDFs.',
                null=True,
                upload_to='company/estimate_pdf/',
            ),
        ),
    ]
