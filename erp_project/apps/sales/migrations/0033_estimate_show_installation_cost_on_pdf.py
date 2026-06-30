from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0032_estimateitem_brand_installation_cost'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='show_installation_cost_on_pdf',
            field=models.BooleanField(
                default=False,
                help_text='If on, PDF shows per-unit installation cost on each line.',
            ),
        ),
    ]
