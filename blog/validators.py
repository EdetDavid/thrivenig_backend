import re

from django.core.exceptions import ValidationError


RAW_HTML_TAG_PATTERN = re.compile(
    r'<\s*/?\s*[A-Za-z][A-Za-z0-9-]*(?=\s|/?>)',
    re.IGNORECASE,
)


def validate_markdown_content(value):
    """Keep articles as inert Markdown instead of accepting embedded HTML."""

    if '\x00' in value:
        raise ValidationError('Article content cannot contain null characters.')
    if RAW_HTML_TAG_PATTERN.search(value):
        raise ValidationError(
            'Raw HTML is not allowed in article content. Use Markdown instead.'
        )
