from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def copy_m2m_to_membership(apps, schema_editor):
    Item = apps.get_model('inventory', 'Item')
    ItemGroupMembership = apps.get_model('inventory', 'ItemGroupMembership')
    Through = Item.item_groups.through
    for row in Through.objects.all().iterator():
        ItemGroupMembership.objects.get_or_create(
            group_id=row.itemgroup_id,
            item_id=row.item_id,
            defaults={'default_quantity': Decimal('1.00'), 'sort_order': 0},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0016_item_selling_price_bound_types'),
    ]

    operations = [
        migrations.CreateModel(
            name='ItemGroupMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('default_quantity', models.DecimalField(
                    decimal_places=2,
                    default=Decimal('1.00'),
                    help_text='Default qty when this group is added to an estimate.',
                    max_digits=10,
                )),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('group', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships',
                    to='inventory.itemgroup',
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='group_memberships',
                    to='inventory.item',
                )),
            ],
            options={
                'verbose_name': 'Group membership',
                'verbose_name_plural': 'Group memberships',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='itemgroupmembership',
            constraint=models.UniqueConstraint(
                fields=('group', 'item'),
                name='inventory_group_item_unique',
            ),
        ),
        migrations.RunPython(copy_m2m_to_membership, noop),
        migrations.RemoveField(
            model_name='item',
            name='item_groups',
        ),
        migrations.AddField(
            model_name='item',
            name='item_groups',
            field=models.ManyToManyField(
                blank=True,
                related_name='items',
                through='inventory.ItemGroupMembership',
                to='inventory.itemgroup',
                verbose_name='Groups',
            ),
        ),
    ]
