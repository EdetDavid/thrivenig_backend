from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import (
    FlightBooking,
    HotelBooking,
    TravelPricingSettings,
    TravelSearchLog,
)
from .services.travel_pricing import (
    TravelPricingError,
    apply_flight_pricing,
)


class TravelAdminAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create(
            username='travel-admin',
            email='admin@example.com',
            is_staff=True,
            is_active=True,
        )
        self.customer = User.objects.create(
            username='traveler',
            email='traveler@example.com',
            is_active=True,
        )
        self.flight_request = FlightBooking.objects.create(
            guest_name='Ada Traveler',
            guest_email='ada@example.com',
            guest_phone='+2348012345678',
            user_details={'name': 'Ada Traveler'},
            flight_details={'origin': 'LOS', 'destination': 'LHR'},
            search_results={
                'id': 'off_123',
                'price': {'currency': 'NGN', 'grandTotal': '250000.00'},
            },
        )
        self.hotel_request = HotelBooking.objects.create(
            user=self.customer,
            user_details={'name': 'Traveler'},
            hotel_details={'name': 'Lagos Hotel'},
        )
        TravelSearchLog.objects.create(
            service_type=TravelSearchLog.SERVICE_FLIGHT,
            criteria={'origin': 'LOS', 'destination': 'LHR'},
            provider='Duffel',
            status=TravelSearchLog.STATUS_SUCCESS,
            result_count=2,
            display_currency='NGN',
        )
        TravelSearchLog.objects.create(
            service_type=TravelSearchLog.SERVICE_HOTEL,
            user=self.customer,
            criteria={'city': 'Lagos'},
            provider='Example Hotels',
            status=TravelSearchLog.STATUS_SUCCESS,
            result_count=3,
            display_currency='NGN',
        )
        self.urls = [
            '/api/travel-admin/overview/',
            '/api/travel-admin/settings/',
            '/api/travel-admin/users/',
            f'/api/travel-admin/users/{self.customer.id}/',
            '/api/travel-admin/flight-searches/',
            '/api/travel-admin/hotel-searches/',
            '/api/travel-admin/flight-requests/',
            '/api/travel-admin/hotel-requests/',
            f'/api/travel-admin/flight-requests/{self.flight_request.id}/',
            f'/api/travel-admin/hotel-requests/{self.hotel_request.id}/',
        ]

    def role_manager_client(self):
        owner = User.objects.create_superuser(
            username='site-owner',
            email='owner@example.com',
            password='password',
        )
        client = APIClient()
        client.force_authenticate(owner)
        return client, owner

    def test_every_travel_admin_endpoint_requires_staff(self):
        anonymous = APIClient()
        regular = APIClient()
        regular.force_authenticate(self.customer)

        for url in self.urls:
            self.assertIn(anonymous.get(url).status_code, (401, 403), url)
            self.assertEqual(regular.get(url).status_code, 403, url)

    def test_staff_can_read_overview_and_paginated_admin_lists(self):
        client = APIClient()
        client.force_authenticate(self.staff)

        overview = client.get('/api/travel-admin/overview/')
        users = client.get('/api/travel-admin/users/')
        flight_searches = client.get('/api/travel-admin/flight-searches/')
        hotel_searches = client.get('/api/travel-admin/hotel-searches/')
        flight_requests = client.get('/api/travel-admin/flight-requests/')
        hotel_requests = client.get('/api/travel-admin/hotel-requests/')

        self.assertEqual(overview.status_code, 200, overview.data)
        self.assertEqual(overview.data['totals']['users'], 2)
        self.assertEqual(overview.data['totals']['flight_searches'], 1)
        self.assertEqual(overview.data['totals']['hotel_searches'], 1)
        self.assertEqual(overview.data['totals']['pending_flight_requests'], 1)
        self.assertEqual(overview.data['pricing']['display_currency'], 'NGN')

        for response in (
            users,
            flight_searches,
            hotel_searches,
            flight_requests,
            hotel_requests,
        ):
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(
                set(response.data),
                {'count', 'next', 'previous', 'results'},
            )

        user_row = next(
            row for row in users.data['results'] if row['id'] == self.customer.id
        )
        self.assertEqual(user_row['flight_request_count'], 0)
        self.assertEqual(user_row['hotel_request_count'], 1)
        self.assertEqual(user_row['search_count'], 1)
        self.assertNotIn('password', user_row)
        self.assertNotIn('token', user_row)
        self.assertEqual(flight_requests.data['results'][0]['reference'], 'TTF-000001')
        self.assertEqual(hotel_requests.data['results'][0]['reference'], 'TTH-000001')

    def test_staff_can_update_pricing_and_request_status_only(self):
        client = APIClient()
        client.force_authenticate(self.staff)

        pricing_response = client.patch(
            '/api/travel-admin/settings/',
            {
                'usd_to_ngn_rate': '1550.2500',
                'flight_markup_mode': 'fixed',
                'flight_markup_percent': '12.50',
                'flight_markup_fixed_ngn': '25000.00',
                'hotel_markup_mode': 'percentage',
                'hotel_markup_percent': '8.00',
                'hotel_markup_fixed_ngn': '15000.00',
            },
            format='json',
        )
        flight_response = client.patch(
            f'/api/travel-admin/flight-requests/{self.flight_request.id}/',
            {'status': FlightBooking.STATUS_CONFIRMED},
            format='json',
        )
        hotel_response = client.patch(
            f'/api/travel-admin/hotel-requests/{self.hotel_request.id}/',
            {'status': HotelBooking.STATUS_CANCELLED},
            format='json',
        )

        self.assertEqual(pricing_response.status_code, 200, pricing_response.data)
        self.assertEqual(pricing_response.data['usd_to_ngn_rate'], '1550.2500')
        self.assertEqual(pricing_response.data['flight_markup_mode'], 'fixed')
        self.assertEqual(
            pricing_response.data['flight_markup_fixed_ngn'],
            '25000.00',
        )
        self.assertEqual(
            pricing_response.data['hotel_markup_mode'],
            'percentage',
        )
        self.assertEqual(pricing_response.data['updated_by']['id'], self.staff.id)
        self.assertEqual(flight_response.status_code, 200, flight_response.data)
        self.assertEqual(flight_response.data['status'], 'confirmed')
        self.assertEqual(hotel_response.status_code, 200, hotel_response.data)
        self.assertEqual(hotel_response.data['status'], 'cancelled')

        invalid_responses = [
            client.patch(
                '/api/travel-admin/settings/',
                {'usd_to_ngn_rate': '0'},
                format='json',
            ),
            client.patch(
                '/api/travel-admin/settings/',
                {'flight_markup_percent': '100.01'},
                format='json',
            ),
            client.patch(
                '/api/travel-admin/settings/',
                {'display_currency': 'USD'},
                format='json',
            ),
            client.patch(
                '/api/travel-admin/settings/',
                {'flight_markup_mode': 'per_passenger'},
                format='json',
            ),
            client.patch(
                '/api/travel-admin/settings/',
                {'hotel_markup_fixed_ngn': '-0.01'},
                format='json',
            ),
            client.patch(
                f'/api/travel-admin/flight-requests/{self.flight_request.id}/',
                {'guest_email': 'attacker@example.com'},
                format='json',
            ),
        ]
        self.assertTrue(
            all(response.status_code == 400 for response in invalid_responses),
            [response.data for response in invalid_responses],
        )

    def test_profile_exposes_staff_flag_without_allowing_it_to_be_changed(self):
        client = APIClient()
        client.force_authenticate(self.staff)

        profile = client.get('/api/profile/')
        attempted_change = client.put(
            '/api/profile/',
            {'is_staff': False, 'first_name': 'Travel'},
            format='json',
        )

        self.assertEqual(profile.status_code, 200)
        self.assertTrue(profile.data['is_staff'])
        self.assertFalse(profile.data['can_manage_admins'])
        self.assertEqual(attempted_change.status_code, 200)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_staff)
        self.assertEqual(self.staff.first_name, 'Travel')

    def test_active_superuser_can_grant_dashboard_admin_access(self):
        client, owner = self.role_manager_client()
        self.customer.set_password('unchanged-password')
        self.customer.save(update_fields=['password'])
        target_token = Token.objects.create(user=self.customer)
        original_password = self.customer.password
        original_email = self.customer.email
        original_permissions = list(
            self.customer.user_permissions.values_list('pk', flat=True)
        )

        response = client.patch(
            f'/api/travel-admin/users/{self.customer.id}/',
            {'is_staff': True},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data),
            {
                'id',
                'username',
                'email',
                'first_name',
                'last_name',
                'full_name',
                'phone',
                'address',
                'is_active',
                'is_staff',
                'role',
                'is_content_manager',
                'can_manage_content',
                'capabilities',
                'can_manage_admins',
                'admin_access_protected',
                'date_joined',
                'last_login',
                'flight_request_count',
                'hotel_request_count',
                'search_count',
            },
        )
        self.assertEqual(response.data['id'], self.customer.id)
        self.assertTrue(response.data['is_staff'])
        self.assertFalse(response.data['can_manage_admins'])
        self.assertFalse(response.data['admin_access_protected'])
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_staff)
        self.assertFalse(self.customer.is_superuser)
        self.assertTrue(self.customer.is_active)
        self.assertEqual(self.customer.email, original_email)
        self.assertEqual(self.customer.password, original_password)
        self.assertEqual(
            list(self.customer.user_permissions.values_list('pk', flat=True)),
            original_permissions,
        )
        self.assertEqual(
            Token.objects.get(user=self.customer).key,
            target_token.key,
        )
        self.assertNotIn('password', response.data)
        self.assertNotIn('token', response.data)

        entry = LogEntry.objects.get(object_id=str(self.customer.id))
        self.assertEqual(entry.user_id, owner.id)
        self.assertEqual(entry.action_flag, CHANGE)
        self.assertEqual(
            entry.change_message,
            'Granted travel admin dashboard access.',
        )

        idempotent_response = client.patch(
            f'/api/travel-admin/users/{self.customer.id}/',
            {'is_staff': True},
            format='json',
        )
        self.assertEqual(idempotent_response.status_code, 200)
        self.assertEqual(
            LogEntry.objects.filter(object_id=str(self.customer.id)).count(),
            1,
        )

    def test_role_endpoint_allows_patch_only_for_authorized_callers(self):
        client, _ = self.role_manager_client()
        url = f'/api/travel-admin/users/{self.customer.id}/'

        responses = [
            client.get(url),
            client.post(url, {'is_staff': True}, format='json'),
            client.put(url, {'is_staff': True}, format='json'),
            client.delete(url),
        ]

        self.assertTrue(
            all(response.status_code == 405 for response in responses),
            [(response.status_code, response.data) for response in responses],
        )

    def test_active_superuser_can_revoke_dashboard_admin_access(self):
        another_admin = User.objects.create_user(
            username='another-admin',
            email='another-admin@example.com',
            is_staff=True,
        )
        another_admin.set_password('unchanged-password')
        another_admin.save(update_fields=['password'])
        permission = Permission.objects.order_by('pk').first()
        another_admin.user_permissions.add(permission)
        target_token = Token.objects.create(user=another_admin)
        original_password = another_admin.password
        original_email = another_admin.email
        original_permissions = list(
            another_admin.user_permissions.values_list('pk', flat=True)
        )
        client, owner = self.role_manager_client()
        target_client = APIClient()
        target_client.credentials(
            HTTP_AUTHORIZATION=f'Token {target_token.key}'
        )

        before_revoke = target_client.get('/api/travel-admin/overview/')

        response = client.patch(
            f'/api/travel-admin/users/{another_admin.id}/',
            {'is_staff': False},
            format='json',
        )

        self.assertEqual(before_revoke.status_code, 200, before_revoke.data)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_staff'])
        self.assertFalse(response.data['admin_access_protected'])
        another_admin.refresh_from_db()
        self.assertFalse(another_admin.is_staff)
        self.assertFalse(another_admin.is_superuser)
        self.assertTrue(another_admin.is_active)
        self.assertEqual(another_admin.email, original_email)
        self.assertEqual(another_admin.password, original_password)
        self.assertEqual(
            list(another_admin.user_permissions.values_list('pk', flat=True)),
            original_permissions,
        )
        self.assertEqual(
            Token.objects.get(user=another_admin).key,
            target_token.key,
        )

        after_revoke = target_client.get('/api/travel-admin/overview/')
        profile = target_client.get('/api/profile/')
        self.assertEqual(after_revoke.status_code, 403, after_revoke.data)
        self.assertEqual(profile.status_code, 200, profile.data)
        self.assertEqual(profile.data['id'], another_admin.id)
        self.assertFalse(profile.data['is_staff'])

        entry = LogEntry.objects.get(object_id=str(another_admin.id))
        self.assertEqual(entry.user_id, owner.id)
        self.assertEqual(entry.action_flag, CHANGE)
        self.assertEqual(
            entry.change_message,
            'Revoked travel admin dashboard access.',
        )

        idempotent_response = client.patch(
            f'/api/travel-admin/users/{another_admin.id}/',
            {'is_staff': False},
            format='json',
        )
        self.assertEqual(idempotent_response.status_code, 200)
        self.assertFalse(idempotent_response.data['is_staff'])
        self.assertEqual(
            LogEntry.objects.filter(object_id=str(another_admin.id)).count(),
            1,
        )

    def test_inactive_staff_admin_access_can_be_revoked(self):
        inactive_admin = User.objects.create_user(
            username='inactive-admin',
            email='inactive-admin@example.com',
            is_active=False,
            is_staff=True,
        )
        client, _ = self.role_manager_client()

        response = client.patch(
            f'/api/travel-admin/users/{inactive_admin.id}/',
            {'is_staff': False},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_active'])
        self.assertFalse(response.data['is_staff'])
        inactive_admin.refresh_from_db()
        self.assertFalse(inactive_admin.is_staff)
        self.assertFalse(inactive_admin.is_active)
        self.assertEqual(
            LogEntry.objects.filter(object_id=str(inactive_admin.id)).count(),
            1,
        )

    def test_regular_user_cannot_change_dashboard_admin_access(self):
        grant_target = User.objects.create_user(username='grant-target')
        revoke_target = User.objects.create_user(
            username='revoke-target',
            is_staff=True,
        )
        client = APIClient()
        client.force_authenticate(self.customer)

        grant_response = client.patch(
            f'/api/travel-admin/users/{grant_target.id}/',
            {'is_staff': True},
            format='json',
        )
        revoke_response = client.patch(
            f'/api/travel-admin/users/{revoke_target.id}/',
            {'is_staff': False},
            format='json',
        )

        self.assertEqual(grant_response.status_code, 403, grant_response.data)
        self.assertEqual(revoke_response.status_code, 403, revoke_response.data)
        grant_target.refresh_from_db()
        revoke_target.refresh_from_db()
        self.assertFalse(grant_target.is_staff)
        self.assertTrue(revoke_target.is_staff)

    def test_ordinary_staff_and_inactive_superuser_cannot_change_admin_access(self):
        inactive_owner = User.objects.create_superuser(
            username='inactive-owner',
            email='inactive-owner@example.com',
            password='password',
        )
        inactive_owner.is_active = False
        inactive_owner.save(update_fields=['is_active'])
        staff_client = APIClient()
        staff_client.force_authenticate(self.staff)
        inactive_owner_client = APIClient()
        inactive_owner_client.force_authenticate(inactive_owner)
        url = f'/api/travel-admin/users/{self.customer.id}/'
        revoke_target = User.objects.create_user(
            username='protected-admin-target',
            is_staff=True,
        )
        revoke_url = f'/api/travel-admin/users/{revoke_target.id}/'

        staff_response = staff_client.patch(
            url,
            {'is_staff': True},
            format='json',
        )
        inactive_owner_response = inactive_owner_client.patch(
            url,
            {'is_staff': True},
            format='json',
        )
        staff_revoke_response = staff_client.patch(
            revoke_url,
            {'is_staff': False},
            format='json',
        )
        inactive_owner_revoke_response = inactive_owner_client.patch(
            revoke_url,
            {'is_staff': False},
            format='json',
        )

        self.assertEqual(staff_response.status_code, 403, staff_response.data)
        self.assertEqual(
            inactive_owner_response.status_code,
            403,
            inactive_owner_response.data,
        )
        self.assertEqual(
            staff_revoke_response.status_code,
            403,
            staff_revoke_response.data,
        )
        self.assertEqual(
            inactive_owner_revoke_response.status_code,
            403,
            inactive_owner_revoke_response.data,
        )
        self.customer.refresh_from_db()
        revoke_target.refresh_from_db()
        self.assertFalse(self.customer.is_staff)
        self.assertTrue(revoke_target.is_staff)

    def test_even_role_manager_cannot_demote_their_own_account(self):
        client, owner = self.role_manager_client()
        other_owner = User.objects.create_superuser(
            username='other-site-owner',
            email='other-owner@example.com',
            password='password',
        )
        other_owner.is_active = False
        other_owner.save(update_fields=['is_active'])

        self_response = client.patch(
            f'/api/travel-admin/users/{owner.id}/',
            {'is_staff': False},
            format='json',
        )
        superuser_response = client.patch(
            f'/api/travel-admin/users/{other_owner.id}/',
            {'is_staff': False},
            format='json',
        )
        users_response = client.get('/api/travel-admin/users/')

        self.assertEqual(self_response.status_code, 400, self_response.data)
        self.assertIn('is_staff', self_response.data)
        self.assertEqual(
            superuser_response.status_code,
            400,
            superuser_response.data,
        )
        self.assertIn('is_staff', superuser_response.data)
        owner.refresh_from_db()
        other_owner.refresh_from_db()
        self.assertTrue(owner.is_staff)
        self.assertTrue(owner.is_superuser)
        self.assertTrue(other_owner.is_staff)
        self.assertTrue(other_owner.is_superuser)
        protected_row = next(
            row
            for row in users_response.data['results']
            if row['id'] == other_owner.id
        )
        self.assertFalse(protected_row['can_manage_admins'])
        self.assertTrue(protected_row['admin_access_protected'])
        self.assertFalse(
            LogEntry.objects.filter(
                object_id__in=(str(owner.id), str(other_owner.id))
            ).exists()
        )

    def test_admin_role_update_rejects_missing_users_and_malformed_payloads(self):
        client, _ = self.role_manager_client()
        url = f'/api/travel-admin/users/{self.customer.id}/'

        not_found = client.patch(
            '/api/travel-admin/users/999999/',
            {'is_staff': True},
            format='json',
        )
        missing_value = client.patch(url, {}, format='json')
        invalid_values = [
            client.patch(url, {'is_staff': value}, format='json')
            for value in ('true', 'false', 1, 0, None)
        ]

        self.assertEqual(not_found.status_code, 404, not_found.data)
        self.assertEqual(missing_value.status_code, 400, missing_value.data)
        self.assertTrue(
            all(response.status_code == 400 for response in invalid_values),
            [response.data for response in invalid_values],
        )
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)

    def test_admin_role_update_rejects_superuser_or_other_field_changes(self):
        client, _ = self.role_manager_client()

        response = client.patch(
            f'/api/travel-admin/users/{self.customer.id}/',
            {
                'is_staff': True,
                'is_superuser': True,
                'is_active': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('is_superuser', response.data)
        self.assertIn('is_active', response.data)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)
        self.assertFalse(self.customer.is_superuser)
        self.assertTrue(self.customer.is_active)

    def test_inactive_user_cannot_be_promoted(self):
        inactive_user = User.objects.create_user(
            username='inactive-user',
            email='inactive@example.com',
            is_active=False,
        )
        client, _ = self.role_manager_client()

        response = client.patch(
            f'/api/travel-admin/users/{inactive_user.id}/',
            {'is_staff': True},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        inactive_user.refresh_from_db()
        self.assertFalse(inactive_user.is_staff)

    def test_profile_exposes_role_management_capability_read_only(self):
        client, owner = self.role_manager_client()

        profile = client.get('/api/profile/')
        attempted_change = client.put(
            '/api/profile/',
            {'can_manage_admins': False, 'first_name': 'Site'},
            format='json',
        )

        self.assertEqual(profile.status_code, 200, profile.data)
        self.assertTrue(profile.data['can_manage_admins'])
        self.assertEqual(attempted_change.status_code, 200)
        owner.refresh_from_db()
        self.assertTrue(owner.is_superuser)
        self.assertEqual(owner.first_name, 'Site')


class TravelPricingAndLoggingTests(TestCase):
    def setUp(self):
        cache.clear()
        TravelPricingSettings.objects.create(
            usd_to_ngn_rate='1500.0000',
            flight_markup_percent='10.00',
            hotel_markup_percent='5.00',
        )

    def test_usd_flight_prices_are_converted_to_ngn_then_marked_up(self):
        supplier_results = {
            'data': [
                {
                    'id': 'off_usd',
                    'price': {
                        'currency': 'USD',
                        'grandTotal': '100.00',
                        'base': '80.00',
                    },
                    'refundCondition': {
                        'allowed': True,
                        'penaltyAmount': '10.00',
                        'penaltyCurrency': 'USD',
                    },
                    'itineraries': [],
                },
                {
                    'id': 'off_ngn',
                    'price': {
                        'currency': 'NGN',
                        'grandTotal': '100000.00',
                        'base': '90000.00',
                    },
                    'itineraries': [],
                },
            ],
            'meta': {'provider': 'Duffel'},
        }

        priced = apply_flight_pricing(supplier_results)

        usd_offer = priced['data'][0]
        ngn_offer = priced['data'][1]
        self.assertEqual(usd_offer['price']['currency'], 'NGN')
        self.assertEqual(usd_offer['price']['grandTotal'], '165000.00')
        self.assertEqual(usd_offer['price']['base'], '132000.00')
        self.assertEqual(
            usd_offer['refundCondition'],
            {
                'allowed': True,
                'penaltyAmount': '15000.00',
                'penaltyCurrency': 'NGN',
            },
        )
        self.assertEqual(ngn_offer['price']['grandTotal'], '110000.00')
        self.assertEqual(priced['meta']['displayCurrency'], 'NGN')
        self.assertNotIn('markup', priced['meta'])
        self.assertEqual(
            supplier_results['data'][0]['price']['grandTotal'],
            '100.00',
            'pricing must not mutate the cached supplier response',
        )

    def test_first_pricing_request_uses_decimal_defaults_safely(self):
        TravelPricingSettings.objects.all().delete()

        priced = apply_flight_pricing(
            {
                'data': [
                    {
                        'price': {
                            'currency': 'USD',
                            'grandTotal': '10.00',
                        }
                    }
                ],
                'meta': {},
            }
        )

        self.assertEqual(priced['data'][0]['price']['currency'], 'NGN')
        self.assertEqual(priced['data'][0]['price']['grandTotal'], '16000.00')

    def test_fixed_flight_markup_is_added_once_to_each_itinerary_total(self):
        pricing = TravelPricingSettings.load()
        pricing.flight_markup_mode = TravelPricingSettings.MARKUP_FIXED
        pricing.flight_markup_percent = Decimal('99.00')
        pricing.flight_markup_fixed_ngn = Decimal('25000.00')
        pricing.save()
        supplier_results = {
            'data': [
                {
                    'price': {
                        'currency': 'USD',
                        'grandTotal': '100.00',
                        'base': '80.00',
                    },
                    'refundCondition': {
                        'allowed': True,
                        'penaltyAmount': '10.00',
                        'penaltyCurrency': 'USD',
                    },
                }
            ],
            'meta': {},
        }

        priced = apply_flight_pricing(supplier_results)

        self.assertEqual(priced['data'][0]['price']['grandTotal'], '175000.00')
        self.assertEqual(priced['data'][0]['price']['base'], '140000.00')
        self.assertEqual(
            priced['data'][0]['refundCondition']['penaltyAmount'],
            '15000.00',
        )
        self.assertEqual(
            supplier_results['data'][0]['price']['grandTotal'],
            '100.00',
        )

    def test_unconfigured_supplier_currency_is_never_mislabeled_as_ngn(self):
        with self.assertRaises(TravelPricingError):
            apply_flight_pricing(
                {
                    'data': [
                        {
                            'price': {
                                'currency': 'GBP',
                                'grandTotal': '100.00',
                            }
                        }
                    ],
                    'meta': {},
                }
            )

    def test_unconfigured_refund_penalty_currency_does_not_hide_usd_offer(self):
        priced = apply_flight_pricing(
            {
                'data': [
                    {
                        'price': {
                            'currency': 'USD',
                            'grandTotal': '100.00',
                        },
                        'refundCondition': {
                            'allowed': True,
                            'penaltyAmount': '25.00',
                            'penaltyCurrency': 'GBP',
                        },
                    }
                ],
                'meta': {},
            }
        )

        self.assertEqual(priced['data'][0]['price']['currency'], 'NGN')
        self.assertEqual(priced['data'][0]['price']['grandTotal'], '165000.00')
        self.assertEqual(
            priced['data'][0]['refundCondition'],
            {
                'allowed': True,
                'penaltyAmount': '25.00',
                'penaltyCurrency': 'GBP',
            },
        )

    @patch('base.views.search_flights')
    def test_public_flight_search_persists_a_sanitized_search_log(self, search):
        search.return_value = {
            'data': [
                {
                    'id': 'off_123',
                    'price': {
                        'currency': 'NGN',
                        'grandTotal': '250000.00',
                        'base': '200000.00',
                    },
                    'itineraries': [],
                }
            ],
            'meta': {
                'provider': 'Duffel',
                'offerRequestId': 'orq_123',
                'displayCurrency': 'NGN',
            },
        }
        departure = timezone.localdate() + timedelta(days=30)

        response = APIClient().post(
            '/api/flight-search/',
            {
                'origin': 'los',
                'destination': 'lhr',
                'departureDate': departure.isoformat(),
                'adults': 1,
                'children': 0,
                'infants': 0,
                'travelClass': 'economy',
            },
            format='json',
            REMOTE_ADDR='203.0.113.10',
        )

        self.assertEqual(response.status_code, 200, response.data)
        log = TravelSearchLog.objects.get()
        self.assertEqual(log.service_type, TravelSearchLog.SERVICE_FLIGHT)
        self.assertEqual(log.status, TravelSearchLog.STATUS_SUCCESS)
        self.assertIsNone(log.user)
        self.assertEqual(log.criteria['origin'], 'LOS')
        self.assertEqual(log.criteria['departureDate'], departure.isoformat())
        self.assertEqual(log.provider, 'duffel')
        self.assertEqual(log.provider_reference, 'orq_123')
        self.assertEqual(log.result_count, 1)
        self.assertEqual(log.display_currency, 'NGN')
        self.assertEqual(log.minimum_price, Decimal('250000.00'))
        self.assertEqual(log.maximum_price, Decimal('250000.00'))
        self.assertTrue(log.client_ip_hash)
        self.assertNotEqual(log.client_ip_hash, '203.0.113.10')
        self.assertEqual(log.pricing_snapshot['displayCurrency'], 'NGN')
        self.assertEqual(log.pricing_snapshot['flightMarkupMode'], 'percentage')
        self.assertEqual(log.pricing_snapshot['flightMarkupPercent'], '10.00')
        self.assertEqual(log.pricing_snapshot['flightMarkupFixedNgn'], '0.00')
