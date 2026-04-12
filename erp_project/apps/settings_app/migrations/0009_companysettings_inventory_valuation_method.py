from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0008_contract_terms_and_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='companysettings',
            name='inventory_valuation_method',
            field=models.CharField(
                choices=[('fifo', 'FIFO'), ('weighted_average', 'Weighted Average')],
                default='weighted_average',
                help_text='Shown on inventory valuation reports.',
                max_length=30,
            ),
        ),
    ]
