from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .roles import CONTENT_MANAGER_GROUP_NAME, user_role


class RegistrationSiteTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def payload(self, username, **overrides):
        payload = {
            'username': username,
            'email': f'{username}@example.com',
            'password': 'password123',
            'first_name': 'New',
            'last_name': 'User',
        }
        payload.update(overrides)
        return payload

    @override_settings(ADMIN_EMAILS=['travel-registrations@example.com'])
    @patch('base.views.send_email')
    def test_omitted_site_preserves_travel_registration(self, send_email):
        response = self.client.post(
            '/api/users/',
            self.payload('travel-registration'),
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('site', response.data)
        self.assertNotIn('password', response.data)
        self.assertEqual(send_email.call_count, 2)
        welcome, agency = send_email.call_args_list
        self.assertEqual(welcome.args[0], 'Welcome to Thrive Travels')
        self.assertEqual(welcome.args[2], ['travel-registration@example.com'])
        self.assertIn('How to Use Your Account', welcome.args[1])
        self.assertEqual(
            agency.args[0],
            'New Thrive Travels User Registered - '
            'travel-registration@example.com',
        )
        self.assertEqual(agency.args[2], ['travel-registrations@example.com'])
        self.assertIn('Thrive Travels platform', agency.args[1])

    @override_settings(
        ADMIN_EMAILS=['travel-registrations@example.com'],
        INSURANCE_AGENCY_EMAILS=['insurance-registrations@example.com'],
    )
    @patch('base.views.send_email')
    def test_explicit_insurance_site_selects_insurance_branding(self, send_email):
        response = self.client.post(
            '/api/users/',
            self.payload('insurance-registration', site='insurance'),
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn('site', response.data)
        self.assertEqual(send_email.call_count, 2)
        welcome, agency = send_email.call_args_list
        self.assertEqual(welcome.args[0], 'Welcome to Thrive Insurance')
        self.assertEqual(
            welcome.args[2],
            ['insurance-registration@example.com'],
        )
        self.assertIn('Welcome to Thrive Insurance!', welcome.args[1])
        self.assertEqual(
            agency.args[0],
            'New Thrive Insurance User Registered - '
            'insurance-registration@example.com',
        )
        self.assertEqual(
            agency.args[2],
            ['insurance-registrations@example.com'],
        )
        self.assertIn('Thrive Insurance platform', agency.args[1])

        user = User.objects.get(username='insurance-registration')
        self.assertEqual(user_role(user), 'traveler')
        self.assertFalse(user.is_staff)
        self.assertFalse(
            user.groups.filter(name=CONTENT_MANAGER_GROUP_NAME).exists()
        )

    @patch('base.views.send_email')
    def test_invalid_site_is_rejected_before_creating_user(self, send_email):
        response = self.client.post(
            '/api/users/',
            self.payload('invalid-site', site='Insurance'),
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('site', response.data)
        self.assertFalse(User.objects.filter(username='invalid-site').exists())
        send_email.assert_not_called()
