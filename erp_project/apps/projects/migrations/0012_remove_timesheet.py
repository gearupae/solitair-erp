from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0011_approval_estimate_project'),
    ]

    operations = [
        migrations.DeleteModel(name='Timesheet'),
    ]
