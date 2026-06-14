from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0019_project_status_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='category',
            field=models.CharField(
                blank=True,
                choices=[('fire', 'Fire'), ('gas', 'Gas'), ('cctv', 'CCTV')],
                default='',
                max_length=20,
                verbose_name='Category',
            ),
        ),
        migrations.AddField(
            model_name='project',
            name='sub_category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('amc', 'AMC'),
                    ('maintenance', 'Maintenance'),
                    ('maintenance_with_amc', 'Maintenance With AMC'),
                    ('project', 'Project'),
                    ('decor', 'Décor'),
                    ('decor_with_amc', 'Décor with AMC'),
                    ('drawing', 'Drawing'),
                    ('rectification', 'Rectification'),
                    ('trading', 'Trading'),
                    ('refilling', 'Refilling'),
                ],
                default='',
                max_length=32,
                verbose_name='Sub category',
            ),
        ),
    ]
