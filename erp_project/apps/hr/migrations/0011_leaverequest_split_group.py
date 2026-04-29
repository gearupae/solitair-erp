from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0010_leaverequest_reference_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='leaverequest',
            name='split_group_id',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
    ]
