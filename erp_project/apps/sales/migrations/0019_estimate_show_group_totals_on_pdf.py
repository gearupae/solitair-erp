from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0018_estimate_rejection_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='show_group_totals_on_pdf',
            field=models.BooleanField(
                default=False,
                help_text='If on, PDF shows a subtotal after each named line-item group.',
            ),
        ),
    ]
