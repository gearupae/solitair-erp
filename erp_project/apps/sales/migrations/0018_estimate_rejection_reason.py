from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0017_estimateproformainvoice'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='rejection_reason',
            field=models.TextField(
                blank=True,
                help_text='Reason given when the approver rejected this estimate.',
            ),
        ),
    ]
