from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from .roles import CONTENT_MANAGER_GROUP_NAME


class ContentManagerRoleAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username='role-owner',
            email='owner@example.com',
            password='password',
        )
        self.target = User.objects.create_user(
            username='content-target',
            email='content@example.com',
            password='password',
            first_name='Content',
            last_name='Target',
        )
        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.url = f'/api/travel-admin/users/{self.target.pk}/'

    def test_superuser_assigns_canonical_roles_and_profile_exposes_capabilities(self):
        assigned = self.owner_client.patch(
            self.url,
            {'role': 'content_manager'},
            format='json',
        )

        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(assigned.data['role'], 'content_manager')
        self.assertFalse(assigned.data['is_staff'])
        self.assertTrue(assigned.data['is_content_manager'])
        self.assertTrue(assigned.data['can_manage_content'])
        self.assertTrue(assigned.data['capabilities']['manage_content'])
        self.target.refresh_from_db()
        self.assertTrue(
            self.target.groups.filter(
                name=CONTENT_MANAGER_GROUP_NAME
            ).exists()
        )

        target_client = APIClient()
        target_client.force_authenticate(self.target)
        profile = target_client.get('/api/profile/')
        self.assertEqual(profile.status_code, 200, profile.data)
        self.assertEqual(profile.data['role'], 'content_manager')
        self.assertTrue(profile.data['is_content_manager'])
        self.assertTrue(profile.data['can_manage_content'])
        self.assertFalse(profile.data['capabilities']['manage_travel_admin'])

        login = APIClient().post(
            '/api/auth/',
            {'username': self.target.username, 'password': 'password'},
            format='json',
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.assertEqual(login.data['user']['role'], 'content_manager')
        self.assertTrue(login.data['user']['can_manage_content'])

        promoted = self.owner_client.patch(
            self.url,
            {'role': 'admin'},
            format='json',
        )
        self.assertEqual(promoted.status_code, 200, promoted.data)
        self.assertEqual(promoted.data['role'], 'admin')
        self.assertTrue(promoted.data['is_staff'])
        self.assertFalse(promoted.data['is_content_manager'])
        self.target.refresh_from_db()
        self.assertFalse(
            self.target.groups.filter(
                name=CONTENT_MANAGER_GROUP_NAME
            ).exists()
        )

        revoked = self.owner_client.patch(
            self.url,
            {'role': 'traveler'},
            format='json',
        )
        self.assertEqual(revoked.status_code, 200, revoked.data)
        self.assertEqual(revoked.data['role'], 'traveler')
        self.assertFalse(revoked.data['is_staff'])
        self.assertFalse(revoked.data['can_manage_content'])

    def test_role_contract_is_strict_and_keeps_legacy_staff_updates(self):
        mixed = self.owner_client.patch(
            self.url,
            {'role': 'content_manager', 'is_staff': False},
            format='json',
        )
        invalid = self.owner_client.patch(
            self.url,
            {'role': 'editor'},
            format='json',
        )

        self.assertEqual(mixed.status_code, 400, mixed.data)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(
            self.target.groups.filter(
                name=CONTENT_MANAGER_GROUP_NAME
            ).exists()
        )

        legacy = self.owner_client.patch(
            self.url,
            {'is_staff': True},
            format='json',
        )
        self.assertEqual(legacy.status_code, 200, legacy.data)
        self.assertEqual(legacy.data['role'], 'admin')
        self.assertTrue(legacy.data['is_staff'])

    def test_inactive_user_cannot_receive_content_access(self):
        self.target.is_active = False
        self.target.save(update_fields=['is_active'])

        response = self.owner_client.patch(
            self.url,
            {'role': 'content_manager'},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(
            Group.objects.get(
                name=CONTENT_MANAGER_GROUP_NAME
            ).user_set.filter(pk=self.target.pk).exists()
        )

    def test_inactive_content_manager_can_have_content_access_revoked(self):
        assigned = self.owner_client.patch(
            self.url,
            {'role': 'content_manager'},
            format='json',
        )
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.target.is_active = False
        self.target.save(update_fields=['is_active'])

        revoked = self.owner_client.patch(
            self.url,
            {'role': 'traveler'},
            format='json',
        )

        self.assertEqual(revoked.status_code, 200, revoked.data)
        self.assertEqual(revoked.data['role'], 'traveler')
        self.assertFalse(revoked.data['is_active'])
        self.assertFalse(revoked.data['is_content_manager'])
        self.assertFalse(revoked.data['can_manage_content'])
        self.target.refresh_from_db()
        self.assertFalse(
            self.target.groups.filter(
                name=CONTENT_MANAGER_GROUP_NAME
            ).exists()
        )
        revoke_log = LogEntry.objects.filter(
            user_id=self.owner.pk,
            object_id=str(self.target.pk),
            action_flag=CHANGE,
        ).order_by('-id').first()
        self.assertIsNotNone(revoke_log)
        self.assertEqual(
            revoke_log.change_message,
            'Revoked content manager dashboard access.',
        )
