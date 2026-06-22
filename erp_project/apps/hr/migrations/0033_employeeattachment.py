from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0032_leavetype_accrue_monthly'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='employee_attachments/%Y/%m/')),
                ('filename', models.CharField(blank=True, max_length=255)),
                (
                    'label',
                    models.CharField(
                        blank=True,
                        help_text='Optional label, e.g. Passport copy, Visa page',
                        max_length=200,
                    ),
                ),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                (
                    'employee',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='attachments',
                        to='hr.employee',
                    ),
                ),
                (
                    'uploaded_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
    ]
