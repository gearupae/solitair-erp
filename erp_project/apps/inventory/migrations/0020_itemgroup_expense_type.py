from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0024_item_subgroup_expense_type'),
        ('inventory', '0019_itemgroup_base_group_sort_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='itemgroup',
            name='expense_type',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional expense category (configured in Settings).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sub_groups',
                to='settings_app.itemsubgroupexpensetype',
            ),
        ),
    ]
