from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def check_production_blog_media_storage(app_configs, **kwargs):
    issues = []
    if not settings.USE_B2_STORAGE:
        issues.append(
            Warning(
                'Blog images use local filesystem storage.',
                hint=(
                    'Set USE_B2_STORAGE=True and configure the B2_* '
                    'variables for durable production blog media.'
                ),
                id='blog.W001',
            )
        )
    if settings.SERVE_MEDIA_FILES:
        issues.append(
            Warning(
                'Django local media serving is enabled.',
                hint=(
                    'Set SERVE_MEDIA_FILES=False in production; the '
                    'application server is not a production media server.'
                ),
                id='blog.W002',
            )
        )
    return issues
