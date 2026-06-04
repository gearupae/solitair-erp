from django.db import migrations, models


def backfill_base_group_sort_order(apps, schema_editor):
    ItemGroup = apps.get_model('inventory', 'ItemGroup')
    ItemBaseGroup = apps.get_model('inventory', 'ItemBaseGroup')
    for base in ItemBaseGroup.objects.all():
        for order, group in enumerate(
            ItemGroup.objects.filter(base_group_id=base.pk).order_by('name', 'pk')
        ):
            group.base_group_sort_order = order
            group.save(update_fields=['base_group_sort_order'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0018_itembasegroup_itemgroup_base_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemgroup',
            name='base_group_sort_order',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Order of this sub-group within its base group (scope of work / estimates).',
            ),
        ),
        migrations.RunPython(backfill_base_group_sort_order, migrations.RunPython.noop),
    ]
