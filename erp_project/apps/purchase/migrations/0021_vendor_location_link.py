from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0020_procurement_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='location_link',
            field=models.URLField(
                blank=True,
                help_text='Google Maps or other map link to the vendor location',
                max_length=500,
                verbose_name='Location link',
            ),
        ),
        migrations.AlterField(
            model_name='vendor',
            name='trn',
            field=models.CharField(
                blank=True,
                help_text='UAE VAT tax registration number',
                max_length=20,
                verbose_name='TRN',
            ),
        ),
    ]
