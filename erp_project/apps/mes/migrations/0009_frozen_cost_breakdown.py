from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mes', '0008_templates_team_pipeline'),
    ]

    operations = [
        migrations.AddField(
            model_name='productionorder',
            name='frozen_labour_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name='productionorder',
            name='frozen_machine_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name='productionorder',
            name='frozen_material_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name='productionorder',
            name='frozen_overhead_cost',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
    ]
