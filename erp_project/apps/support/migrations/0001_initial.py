# Generated manually for support module

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contracts', '0004_contract_terms_and_defaults'),
        ('crm', '0017_crmleadkanbanstage_is_site_visit'),
        ('hr', '0039_employeeremark_point_types'),
        ('projects', '0021_project_checklist'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SupportTicketKanbanStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('sort_order', models.PositiveIntegerField(db_index=True, default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('is_closed', models.BooleanField(default=False, help_text='If checked, tickets in this column are treated as closed/resolved.')),
            ],
            options={
                'verbose_name': 'Support kanban stage',
                'verbose_name_plural': 'Support kanban stages',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='SupportTicket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('ticket_number', models.CharField(editable=False, max_length=50, unique=True)),
                ('subject', models.CharField(max_length=255)),
                ('link_type', models.CharField(choices=[('customer', 'Customer'), ('project', 'Project'), ('amc', 'AMC')], default='customer', max_length=20)),
                ('opened_date', models.DateField()),
                ('priority', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('urgent', 'Urgent')], default='medium', max_length=20)),
                ('description', models.TextField(blank=True)),
                ('amc_contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_tickets', to='contracts.contract', verbose_name='AMC contract')),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_support_tickets', to='hr.employee')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_supportticket_created', to=settings.AUTH_USER_MODEL)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_tickets', to='crm.customer')),
                ('kanban_stage', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tickets', to='support.supportticketkanbanstage')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_tickets', to='projects.project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_supportticket_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-opened_date', '-created_at'],
            },
        ),
    ]
