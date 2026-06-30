from django.db import migrations


DEFAULT_STAGES = [
    ('new', 'New', 10, False),
    ('in-progress', 'In Progress', 20, False),
    ('waiting', 'Waiting on Customer', 30, False),
    ('resolved', 'Resolved', 40, False),
    ('closed', 'Closed', 50, True),
]


def seed_support_stages(apps, schema_editor):
    Stage = apps.get_model('support', 'SupportTicketKanbanStage')
    for slug, name, sort_order, is_closed in DEFAULT_STAGES:
        Stage.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'sort_order': sort_order,
                'is_active': True,
                'is_closed': is_closed,
            },
        )


def unseed_support_stages(apps, schema_editor):
    Stage = apps.get_model('support', 'SupportTicketKanbanStage')
    Stage.objects.filter(slug__in=[s[0] for s in DEFAULT_STAGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('support', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_support_stages, unseed_support_stages),
    ]
