from django.db import migrations, models


def convert_remark_types(apps, schema_editor):
    EmployeeRemark = apps.get_model('hr', 'EmployeeRemark')
    EmployeeRemark.objects.filter(remark_type='positive').update(remark_type='plus')
    EmployeeRemark.objects.filter(remark_type='general').update(remark_type='plus')


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0038_employeeremark'),
    ]

    operations = [
        migrations.RunPython(convert_remark_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='employeeremark',
            name='remark_type',
            field=models.CharField(
                choices=[('plus', 'Plus point'), ('negative', 'Negative point')],
                default='plus',
                max_length=20,
            ),
        ),
    ]
