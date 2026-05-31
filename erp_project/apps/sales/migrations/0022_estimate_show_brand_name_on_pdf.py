from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0021_estimate_work_classification_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='show_brand_name_on_pdf',
            field=models.BooleanField(
                default=False,
                help_text='If on, PDF shows the inventory item brand name on each line.',
            ),
        ),
    ]
