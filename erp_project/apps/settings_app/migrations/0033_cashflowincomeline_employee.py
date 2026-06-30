from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0040_alter_employee_options_and_more'),
        ('settings_app', '0032_cashflow_month_sheet'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashflowincomeline',
            name='employee',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cashflow_income_lines',
                to='hr.employee',
            ),
        ),
    ]
