from django.contrib.auth.models import Group


CONTENT_MANAGER_GROUP_NAME = 'Content Managers'

ROLE_TRAVELER = 'traveler'
ROLE_CONTENT_MANAGER = 'content_manager'
ROLE_ADMIN = 'admin'
ROLE_CHOICES = (
    (ROLE_TRAVELER, 'Traveler'),
    (ROLE_CONTENT_MANAGER, 'Content manager'),
    (ROLE_ADMIN, 'Administrator'),
)


def is_content_manager(user):
    """Return whether a user has the canonical content-manager assignment."""
    if not user or not getattr(user, 'pk', None):
        return False

    prefetched_groups = getattr(
        user,
        '_prefetched_objects_cache',
        {},
    ).get('groups')
    if prefetched_groups is not None:
        return any(
            group.name == CONTENT_MANAGER_GROUP_NAME
            for group in prefetched_groups
        )

    return user.groups.filter(name=CONTENT_MANAGER_GROUP_NAME).exists()


def user_role(user):
    if user and user.is_staff:
        return ROLE_ADMIN
    if is_content_manager(user):
        return ROLE_CONTENT_MANAGER
    return ROLE_TRAVELER


def can_manage_content(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or is_content_manager(user))
    )


def assign_user_role(user, role):
    """Apply one canonical role without changing unrelated account data."""
    if role not in {choice[0] for choice in ROLE_CHOICES}:
        raise ValueError(f'Unknown user role: {role}')

    content_group, _ = Group.objects.get_or_create(
        name=CONTENT_MANAGER_GROUP_NAME
    )
    should_be_staff = role == ROLE_ADMIN
    if user.is_staff != should_be_staff:
        user.is_staff = should_be_staff
        user.save(update_fields=['is_staff'])

    if role == ROLE_CONTENT_MANAGER:
        user.groups.add(content_group)
    else:
        user.groups.remove(content_group)

    return user
