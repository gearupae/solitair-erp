from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0035_cashflow_month_sheet'),
        ('settings_app', '0033_cashflowincomeline_employee'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashflowincomeline',
            name='estimate',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cashflow_income_lines',
                to='sales.estimate',
            ),
        ),
    ]
