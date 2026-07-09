from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0028_item_warehouse_storage'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='no_overhead',
            field=models.BooleanField(
                default=False,
                help_text='When set, estimate lines using this item default to no overhead markup.',
                verbose_name='No overhead calculation',
            ),
        ),
    ]
