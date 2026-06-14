from django.db import migrations, models


def migrate_in_progress_to_ongoing(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    Project.objects.filter(status='in_progress').update(status='ongoing')


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0018_project_conversion_approval'),
    ]

    operations = [
        migrations.RunPython(migrate_in_progress_to_ongoing, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='project',
            name='status',
            field=models.CharField(
                choices=[
                    ('planning', 'Planning'),
                    ('ongoing', 'ongoing'),
                    ('on_hold', 'On Hold'),
                    ('completed', 'Completed'),
                    ('completed_payment_pending', 'Completed Payment Pending'),
                    ('ongoing_payment_received', 'ongoing payment received'),
                    ('draft', 'Draft'),
                    ('cancelled', 'Cancelled'),
                ],
                default='planning',
                max_length=32,
            ),
        ),
    ]
