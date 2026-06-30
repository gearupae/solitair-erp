# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0002_seed_kanban_stages'),
    ]

    operations = [
        migrations.AddField(
            model_name='supportticket',
            name='requester_email',
            field=models.EmailField(blank=True),
        ),
        migrations.AddField(
            model_name='supportticket',
            name='requester_name',
            field=models.CharField(
                blank=True,
                help_text='Name or company entered on the public support form.',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='supportticket',
            name='requester_phone',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='supportticket',
            name='submitted_via_public',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='supportticket',
            name='link_type',
            field=models.CharField(
                choices=[
                    ('customer', 'Customer'),
                    ('project', 'Project'),
                    ('amc', 'AMC'),
                    ('unlinked', 'General'),
                ],
                default='customer',
                max_length=20,
            ),
        ),
    ]
