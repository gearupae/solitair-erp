from django.db import migrations, models


def seed_inventory_knowledge(apps, schema_editor):
    AiModuleKnowledge = apps.get_model('core', 'AiModuleKnowledge')
    AiModuleKnowledge.objects.get_or_create(
        module='inventory',
        defaults={
            'content': (
                'UAE inventory compliance: block expired batches from sale; VAT-adjust stock '
                'write-offs per FTA; maintain lot traceability for regulated categories; '
                'reconcile GL 1500 with FIFO valuation monthly; escalate negative stock immediately.'
            ),
            'auto_run_enabled': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_aimoduleknowledge_auto_run_enabled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aimoduleknowledge',
            name='module',
            field=models.CharField(
                choices=[
                    ('purchase_request', 'Purchase request'),
                    ('purchase_order', 'Purchase order'),
                    ('estimate', 'Quotation / estimate'),
                    ('project', 'Project'),
                    ('employee', 'Employee'),
                    ('inventory', 'Inventory'),
                ],
                max_length=40,
                unique=True,
            ),
        ),
        migrations.RunPython(seed_inventory_knowledge, migrations.RunPython.noop),
    ]
