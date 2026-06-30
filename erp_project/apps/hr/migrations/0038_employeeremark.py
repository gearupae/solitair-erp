from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('hr', '0037_employee_allowance_expense'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeRemark',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField()),
                ('remark_type', models.CharField(
                    choices=[('positive', 'Good point'), ('negative', 'Concern'), ('general', 'General')],
                    default='general',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='employee_remarks_added',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('employee', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='remarks',
                    to='hr.employee',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
