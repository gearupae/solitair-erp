import uuid

from django.db import migrations, models


def assign_checklist_tokens(apps, schema_editor):
    Project = apps.get_model('projects', 'Project')
    for row in Project.objects.all().iterator():
        row.checklist_public_token = uuid.uuid4()
        row.save(update_fields=['checklist_public_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0020_project_category_sub_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='checklist_public_token',
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(assign_checklist_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='project',
            name='checklist_public_token',
            field=models.UUIDField(db_index=True, editable=False, unique=True),
        ),
        migrations.CreateModel(
            name='ProjectChecklistItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('text', models.CharField(max_length=500)),
                ('item_date', models.DateField()),
                ('is_flagged_red', models.BooleanField(default=False, help_text='When set, row displays red (issue flagged). Otherwise green.')),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created', to='auth.user')),
                ('project', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='checklist_items', to='projects.project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated', to='auth.user')),
            ],
            options={
                'ordering': ['-item_date', '-sort_order', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProjectChecklistUpload',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('file', models.FileField(max_length=500, upload_to='project_checklist/%Y/%m/')),
                ('original_filename', models.CharField(blank=True, max_length=255)),
                ('note', models.CharField(blank=True, max_length=500)),
                ('checklist_item', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='uploads', to='projects.projectchecklistitem')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created', to='auth.user')),
                ('project', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='checklist_uploads', to='projects.project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_updated', to='auth.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
