# Generated manually for ILOE policy and deduction line code normalization

from django.db import migrations, models


def forwards_iloe_code(apps, schema_editor):
    PayrollDeductionLine = apps.get_model('hr', 'PayrollDeductionLine')
    PayrollDeductionLine.objects.filter(code='iloe').update(code='ILOE')


def backwards_iloe_code(apps, schema_editor):
    PayrollDeductionLine = apps.get_model('hr', 'PayrollDeductionLine')
    PayrollDeductionLine.objects.filter(code='ILOE').update(code='iloe')


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0019_payroll_template_basic_cleanup'),
    ]

    operations = [
        migrations.AddField(
            model_name='payrollsettings',
            name='iloe_deduct_via_payroll',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'If enabled, UAE ILOE (premium plus 5% VAT) is deducted from net salary. '
                    'If disabled, the payslip shows the amount as a reminder only; employees typically pay via iloe.ae.'
                ),
            ),
        ),
        migrations.RunPython(forwards_iloe_code, backwards_iloe_code),
    ]
