from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0027_project_technicians_and_attendance_project'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='attendancerecord',
            unique_together=set(),
        ),
        migrations.AlterModelOptions(
            name='attendancerecord',
            options={'ordering': ['-date', '-check_in', '-pk']},
        ),
    ]
