from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0001_initial'),
        ('contracts', '0005_contractdocumentexpiry'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='salesperson',
            field=models.ForeignKey(
                blank=True,
                help_text='Salesperson responsible for this AMC (independent of customer assignment).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='contracts',
                to='hr.employee',
            ),
        ),
        migrations.AddField(
            model_name='contract',
            name='amc_category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('fire_alarm', 'Fire Alarm'),
                    ('gas', 'Gas'),
                    ('cctv', 'CCTV'),
                    ('general_maintenance', 'General Maintenance'),
                ],
                help_text='AMC service category (Fire Alarm, Gas, CCTV, etc.).',
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name='contract',
            name='service_site',
            field=models.TextField(
                blank=True,
                help_text='Building, address, and emirate/area where AMC work is performed.',
            ),
        ),
        migrations.AddField(
            model_name='contract',
            name='planned_visits',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Number of planned PPM visits for this contract period.',
            ),
        ),
        migrations.AlterField(
            model_name='contract',
            name='remind_before_days',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Reminder this many days before end date',
            ),
        ),
    ]
