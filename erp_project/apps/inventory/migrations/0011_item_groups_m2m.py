# Generated migration — ItemGroup M2M, migrate group_label then drop it

from django.db import migrations, models


def migrate_group_labels(apps, schema_editor):
    Item = apps.get_model('inventory', 'Item')
    ItemGroup = apps.get_model('inventory', 'ItemGroup')
    Through = Item.item_groups.through
    seen = {}
    for item in Item.objects.exclude(group_label='').iterator():
        raw = (item.group_label or '').strip()[:200]
        if not raw:
            continue
        if raw not in seen:
            g, _ = ItemGroup.objects.get_or_create(name=raw)
            seen[raw] = g.pk
        Through.objects.get_or_create(item_id=item.pk, itemgroup_id=seen[raw])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0010_item_group_label'),
    ]

    operations = [
        migrations.CreateModel(
            name='ItemGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
            ],
            options={
                'verbose_name': 'Item group',
                'verbose_name_plural': 'Item groups',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='item',
            name='item_groups',
            field=models.ManyToManyField(blank=True, related_name='items', to='inventory.itemgroup', verbose_name='Groups'),
        ),
        migrations.RunPython(migrate_group_labels, noop_reverse),
        migrations.RemoveField(
            model_name='item',
            name='group_label',
        ),
    ]
