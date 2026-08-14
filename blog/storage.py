from django.core.files.storage import storages
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.functional import LazyObject, empty


class BlogMediaStorage(LazyObject):
    """Lazy proxy for the storage alias dedicated to public blog images."""

    def _setup(self):
        self._wrapped = storages['blog_media']

    def reset(self):
        self._wrapped = empty

    def deconstruct(self):
        return ('blog.storage.BlogMediaStorage', (), {})


blog_media_storage = BlogMediaStorage()


@receiver(setting_changed, dispatch_uid='blog.reset_blog_media_storage')
def reset_blog_media_storage(*, setting, **kwargs):
    if setting == 'STORAGES':
        blog_media_storage.reset()
