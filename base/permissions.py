from rest_framework.permissions import BasePermission

from .roles import can_manage_content


class IsActiveSuperuser(BasePermission):
    """Restrict security-sensitive role management to active site owners."""

    message = 'Only an active site owner can manage dashboard roles.'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_superuser
        )


class CanManageContent(BasePermission):
    """Allow active travel admins and canonical content managers."""

    message = 'Content manager access is required.'

    def has_permission(self, request, view):
        return can_manage_content(request.user)
