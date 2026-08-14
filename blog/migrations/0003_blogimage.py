import blog.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('blog', '0002_blogpostview'),
    ]

    operations = [
        migrations.CreateModel(
            name='BlogImage',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'image',
                    models.ImageField(upload_to=blog.models.blog_image_upload_to),
                ),
                ('width', models.PositiveIntegerField()),
                ('height', models.PositiveIntegerField()),
                ('content_type', models.CharField(max_length=20)),
                ('size_bytes', models.PositiveBigIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'uploaded_by',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='blog_images',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={'ordering': ('-created_at', '-id')},
        ),
    ]
