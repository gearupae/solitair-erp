# Manual migration: Employee company/location + expanded UAE/KSA compliance

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def map_nitaqat_green_to_mid(apps, schema_editor):
    KSA = apps.get_model('hr', 'KSACompliance')
    KSA.objects.filter(nitaqat_category='green').update(nitaqat_category='mid_green')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0011_company_entity'),
        ('hr', '0005_hr_extended_attendance_compliance'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='employees',
                to='settings_app.company',
            ),
        ),
        migrations.AddField(
            model_name='employee',
            name='location',
            field=models.CharField(
                choices=[('uae', 'UAE'), ('ksa', 'KSA'), ('other', 'Other')],
                default='uae',
                max_length=10,
            ),
        ),
        migrations.RenameField(
            model_name='uaecompliance',
            old_name='insurance_expiry',
            new_name='medical_insurance_expiry',
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='emirates_id_expiry',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='visa_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('employment', 'Employment'),
                    ('residence', 'Residence'),
                    ('investor', 'Investor'),
                    ('other', 'Other'),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='medical_insurance_policy_number',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='unified_number',
            field=models.CharField(blank=True, help_text='15-digit UAE UID', max_length=15),
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='iloe_applicable',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='uaecompliance',
            name='gratuity_applicable',
            field=models.BooleanField(default=True),
        ),
        migrations.RenameField(
            model_name='ksacompliance',
            old_name='gosi_registration_number',
            new_name='gosi_number',
        ),
        migrations.AlterField(
            model_name='ksacompliance',
            name='iqama_number',
            field=models.CharField(blank=True, max_length=9),
        ),
        migrations.AlterField(
            model_name='ksacompliance',
            name='nitaqat_category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('platinum', 'Platinum'),
                    ('high_green', 'High Green'),
                    ('mid_green', 'Mid Green'),
                    ('low_green', 'Low Green'),
                    ('yellow', 'Yellow'),
                    ('red', 'Red'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(map_nitaqat_green_to_mid, noop_reverse),
        migrations.AddField(
            model_name='ksacompliance',
            name='iqama_profession',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='work_permit_number',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='work_permit_expiry',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='work_permit_classification',
            field=models.CharField(
                blank=True,
                choices=[
                    ('professional', 'Professional'),
                    ('skilled', 'Skilled'),
                    ('semi_skilled', 'Semi-Skilled'),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='passport_number',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='passport_expiry',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='medical_insurance_provider',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='medical_insurance_policy_number',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='medical_insurance_expiry',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='absher_id',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='nationality',
            field=models.CharField(
                choices=[('saudi', 'Saudi'), ('non_saudi', 'Non-Saudi')],
                default='non_saudi',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='gosi_applicable',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='qiwa_contract_registered',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ksacompliance',
            name='mudad_wps_enrolled',
            field=models.BooleanField(default=False),
        ),
    ]
