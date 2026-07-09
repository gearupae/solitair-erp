from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0023_inspection_checklist'),
        ('sales', '0037_estimate_contract_body'),
        ('contracts', '0006_contract_amc_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='source_estimate',
            field=models.ForeignKey(
                blank=True,
                help_text='Won quotation this AMC was created from.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='amc_contracts',
                to='sales.estimate',
            ),
        ),
        migrations.AddField(
            model_name='contract',
            name='project',
            field=models.ForeignKey(
                blank=True,
                help_text='Linked job / project for this AMC.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='amc_contracts',
                to='projects.project',
            ),
        ),
    ]
