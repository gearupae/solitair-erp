from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0005_hr_extended_attendance_compliance'),
        ('sales', '0030_estimate_public_create_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='estimation_reference_number',
            field=models.CharField(
                blank=True,
                default='',
                max_length=100,
                verbose_name='Estimation reference number',
            ),
        ),
        migrations.AddField(
            model_name='estimate',
            name='sales_engineer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sales_engineer_estimates',
                to='hr.employee',
                verbose_name='Sales engineer',
            ),
        ),
    ]
