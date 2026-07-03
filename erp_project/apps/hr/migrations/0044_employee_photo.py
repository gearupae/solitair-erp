from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0043_employee_additional_contact'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='photo',
            field=models.ImageField(
                blank=True,
                help_text='Employee profile photo (JPEG, PNG, or WebP).',
                max_length=500,
                null=True,
                upload_to='employee_photos/%Y/%m/',
            ),
        ),
    ]
