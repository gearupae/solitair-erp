"""Public hourly estimate create link and submitted_via_public_link flag."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0029_project_retention'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='submitted_via_public_link',
            field=models.BooleanField(
                default=False,
                help_text='Created through the hourly public estimate submission link.',
            ),
        ),
        migrations.CreateModel(
            name='EstimatePublicCreateLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Public estimate create link',
                'verbose_name_plural': 'Public estimate create links',
                'ordering': ['-created_at'],
            },
        ),
    ]
