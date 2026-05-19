"""Optional custom group label on items (bulk assign + filter)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_storage_location_and_item_enhancements'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='group_label',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Optional label to bundle items for filtering and bulk actions.',
                max_length=200,
                verbose_name='Group',
            ),
        ),
    ]
