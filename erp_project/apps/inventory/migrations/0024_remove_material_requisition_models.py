from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0023_repair_material_requisition_tables'),
    ]

    operations = [
        migrations.DeleteModel(
            name='MaterialRequisitionIssueLine',
        ),
        migrations.DeleteModel(
            name='MaterialRequisitionIssue',
        ),
    ]
