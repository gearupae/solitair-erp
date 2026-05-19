"""Lead pipeline kanban stages + Customer.lead_kanban_stage."""

from django.db import migrations, models
import django.db.models.deletion


def seed_kanban_stages(apps, schema_editor):
    CrmLeadKanbanStage = apps.get_model('crm', 'CrmLeadKanbanStage')
    rows = [
        ('Hot', 'hot', 10, False),
        ('Warm', 'warm', 20, False),
        ('Cold', 'cold', 30, False),
        ('Lost', 'lost', 40, False),
        ('Won', 'won', 50, True),
    ]
    for name, slug, order, conv in rows:
        CrmLeadKanbanStage.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'sort_order': order,
                'is_active': True,
                'converts_to_customer': conv,
            },
        )


def backfill_lead_stages(apps, schema_editor):
    Customer = apps.get_model('crm', 'Customer')
    CrmLeadKanbanStage = apps.get_model('crm', 'CrmLeadKanbanStage')
    first = (
        CrmLeadKanbanStage.objects.filter(
            is_active=True,
            converts_to_customer=False,
        )
        .order_by('sort_order', 'id')
        .first()
    )
    if first:
        Customer.objects.filter(
            customer_type='lead',
            lead_kanban_stage__isnull=True,
        ).update(lead_kanban_stage_id=first.id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0009_alter_customer_trn_document'),
    ]

    operations = [
        migrations.CreateModel(
            name='CrmLeadKanbanStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('sort_order', models.PositiveIntegerField(db_index=True, default=0)),
                ('is_active', models.BooleanField(default=True)),
                (
                    'converts_to_customer',
                    models.BooleanField(
                        default=False,
                        help_text='If checked, leads dropped in the “Won” zone become customers.',
                    ),
                ),
            ],
            options={
                'ordering': ['sort_order', 'id'],
                'verbose_name': 'CRM lead kanban stage',
                'verbose_name_plural': 'CRM lead kanban stages',
            },
        ),
        migrations.RunPython(seed_kanban_stages, noop_reverse),
        migrations.AddField(
            model_name='customer',
            name='lead_kanban_stage',
            field=models.ForeignKey(
                blank=True,
                help_text='Pipeline column for leads (customers do not use this).',
                limit_choices_to={'converts_to_customer': False},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='leads',
                to='crm.crmleadkanbanstage',
            ),
        ),
        migrations.RunPython(backfill_lead_stages, noop_reverse),
    ]
