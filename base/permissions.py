from rest_framework.permissions import BasePermission


class IsActiveSuperuser(BasePermission):
    """Restrict security-sensitive role management to active site owners."""

    message = 'Only an active site owner can manage admin access.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_superuser
        )
