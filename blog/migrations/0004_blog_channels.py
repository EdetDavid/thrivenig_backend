from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0003_blogimage'),
    ]

    operations = [
        migrations.AddField(
            model_name='blogpost',
            name='channel',
            field=models.CharField(
                choices=[
                    ('travel', 'Travel'),
                    ('insurance', 'Insurance'),
                ],
                db_index=True,
                default='travel',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='blogimage',
            name='channel',
            field=models.CharField(
                choices=[
                    ('travel', 'Travel'),
                    ('insurance', 'Insurance'),
                ],
                db_index=True,
                default='travel',
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name='blogpost',
            name='slug',
            field=models.SlugField(max_length=220),
        ),
        migrations.RemoveConstraint(
            model_name='blogpost',
            name='blog_post_slug_ci_uniq',
        ),
        migrations.RemoveIndex(
            model_name='blogpost',
            name='blog_post_status_pub',
        ),
        migrations.RemoveIndex(
            model_name='blogpost',
            name='blog_post_cat_pub',
        ),
        migrations.AddConstraint(
            model_name='blogpost',
            constraint=models.UniqueConstraint(
                'channel',
                Lower('slug'),
                name='blog_post_chan_slug_ci_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(
                fields=['channel', 'status', '-published_at'],
                name='blog_post_chan_status_pub',
            ),
        ),
        migrations.AddIndex(
            model_name='blogpost',
            index=models.Index(
                fields=['channel', 'category', '-published_at'],
                name='blog_post_chan_cat_pub',
            ),
        ),
    ]
