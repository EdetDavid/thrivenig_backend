import blog.models
import blog.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0004_blog_channels'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='blogimage',
                    name='image',
                    field=models.ImageField(
                        storage=blog.storage.BlogMediaStorage(),
                        upload_to=blog.models.blog_image_upload_to,
                    ),
                ),
            ],
        ),
    ]
