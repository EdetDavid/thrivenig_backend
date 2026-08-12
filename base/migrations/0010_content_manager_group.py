from django.db import migrations


CONTENT_MANAGER_GROUP_NAME = 'Content Managers'


def create_content_manager_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name=CONTENT_MANAGER_GROUP_NAME)


def remove_content_manager_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name=CONTENT_MANAGER_GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('base', '0009_travel_pricing_fixed_markup_modes'),
    ]

    operations = [
        migrations.RunPython(
            create_content_manager_group,
            remove_content_manager_group,
        ),
    ]
