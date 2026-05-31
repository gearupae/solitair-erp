from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0015_itemgroup_hide_items_on_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='minimum_selling_price_type',
            field=models.CharField(
                choices=[('amount', 'Amount'), ('percent', 'Percentage')],
                default='amount',
                help_text='Whether minimum is a fixed amount (AED) or % of selling price',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='item',
            name='maximum_selling_price_type',
            field=models.CharField(
                choices=[('amount', 'Amount'), ('percent', 'Percentage')],
                default='amount',
                help_text='Whether maximum is a fixed amount (AED) or % of selling price',
                max_length=10,
            ),
        ),
    ]
