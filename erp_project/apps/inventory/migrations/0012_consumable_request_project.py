# Generated manually — optional project link on consumable requests

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
        ('inventory', '0011_item_groups_m2m'),
    ]

    operations = [
        migrations.AddField(
            model_name='consumablerequest',
            name='project',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional project this consumable request is for.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='consumable_requests',
                to='projects.project',
            ),
        ),
    ]
