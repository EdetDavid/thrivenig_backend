from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from .models import (
    HotelBooking,
    HotelListing,
    TravelPricingSettings,
    TravelSearchLog,
)


def search_criteria(**overrides):
    check_in = timezone.localdate() + timedelta(days=10)
    values = {
        'city': 'Lagos',
        'checkInDate': check_in.isoformat(),
        'checkOutDate': (check_in + timedelta(days=3)).isoformat(),
        'rooms': 2,
        'guests': 3,
    }
    values.update(overrides)
    return values


def create_listing(**overrides):
    values = {
        'name': 'Lagoon Business Hotel',
        'city': 'Lagos',
        'country': 'Nigeria',
        'address': '1 Marina Road',
        'room_type': 'Standard King',
        'nightly_amount': Decimal('100.00'),
        'source_currency': HotelListing.CURRENCY_USD,
        'max_guests': 2,
        'star_rating': 4,
        'image_url': 'https://images.example.com/lagoon.jpg',
        'amenities': ['Wi-Fi', 'Breakfast'],
        'available_rooms': 4,
        'active': True,
        'test_data': False,
    }
    values.update(overrides)
    return HotelListing.objects.create(**values)


@override_settings(
    HOTEL_SEARCH_PROVIDER='local',
    ALLOW_HOTEL_TEST_DATA=False,
)
class HotelSearchAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.listing = create_listing()
        TravelPricingSettings.objects.update_or_create(
            pk=1,
            defaults={
                'usd_to_ngn_rate': Decimal('1500.0000'),
                'flight_markup_percent': Decimal('0.00'),
                'hotel_markup_percent': Decimal('10.00'),
            },
        )

    def test_public_search_returns_exact_honest_shape_and_logs_priced_result(self):
        response = self.client.post(
            '/api/hotel-search/',
            search_criteria(),
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['meta']['provider'], 'Thrive inventory')
        self.assertIs(response.data['meta']['live'], False)
        self.assertIs(response.data['meta']['testData'], False)
        self.assertEqual(response.data['meta']['displayCurrency'], 'NGN')
        self.assertTrue(response.data['meta']['checkedAt'])
        self.assertEqual(len(response.data['data']), 1)
        result = response.data['data'][0]
        self.assertEqual(
            set(result),
            {
                'id',
                'searchResultId',
                'listingId',
                'provider',
                'source',
                'liveMode',
                'testData',
                'expiresAt',
                'checkedAt',
                'property',
                'room',
                'stay',
                'price',
                'availability',
            },
        )
        self.assertEqual(result['id'], f'hotel-{self.listing.pk}')
        self.assertEqual(result['searchResultId'], f'local-hotel-{self.listing.pk}')
        self.assertEqual(result['listingId'], self.listing.pk)
        self.assertEqual(result['provider'], 'Thrive inventory')
        self.assertEqual(result['source'], 'local')
        self.assertIs(result['liveMode'], False)
        self.assertIs(result['testData'], False)
        self.assertIsNone(result['expiresAt'])
        self.assertTrue(result['checkedAt'])
        self.assertEqual(
            result['property'],
            {
                'name': 'Lagoon Business Hotel',
                'city': 'Lagos',
                'country': 'Nigeria',
                'address': '1 Marina Road',
                'starRating': 4,
                'imageUrl': 'https://images.example.com/lagoon.jpg',
                'amenities': ['Wi-Fi', 'Breakfast'],
            },
        )
        self.assertEqual(
            result['room'],
            {
                'type': 'Standard King',
                'maxGuests': 2,
                'availableRooms': 4,
            },
        )
        self.assertEqual(result['stay']['nights'], 3)
        self.assertEqual(result['stay']['rooms'], 2)
        self.assertEqual(result['stay']['guests'], 3)
        self.assertEqual(
            result['price'],
            {
                'currency': 'NGN',
                'grandTotal': '990000.00',
                'nightly': '165000.00',
            },
        )
        self.assertEqual(
            result['availability'],
            {
                'status': 'on_request',
                'message': 'Availability and final price will be confirmed.',
            },
        )

        search_log = TravelSearchLog.objects.get()
        self.assertEqual(search_log.service_type, TravelSearchLog.SERVICE_HOTEL)
        self.assertEqual(search_log.status, TravelSearchLog.STATUS_SUCCESS)
        self.assertEqual(search_log.provider, 'Thrive inventory')
        self.assertEqual(search_log.result_count, 1)
        self.assertEqual(search_log.display_currency, 'NGN')
        self.assertEqual(search_log.minimum_price, Decimal('990000.00'))
        self.assertEqual(search_log.maximum_price, Decimal('990000.00'))

    def test_fixed_hotel_markup_is_added_once_to_the_whole_stay(self):
        pricing = TravelPricingSettings.load()
        pricing.hotel_markup_mode = TravelPricingSettings.MARKUP_FIXED
        pricing.hotel_markup_percent = Decimal('100.00')
        pricing.hotel_markup_fixed_ngn = Decimal('60000.00')
        pricing.save()

        response = self.client.post(
            '/api/hotel-search/',
            search_criteria(),
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        price = response.data['data'][0]['price']
        # USD 100 x NGN 1,500 x 3 nights x 2 rooms, plus NGN 60,000 once.
        self.assertEqual(price['grandTotal'], '960000.00')
        self.assertEqual(price['nightly'], '160000.00')

    def test_ngn_prices_receive_hotel_markup_without_currency_conversion(self):
        self.listing.source_currency = HotelListing.CURRENCY_NGN
        self.listing.nightly_amount = Decimal('50000.00')
        self.listing.save(update_fields=['source_currency', 'nightly_amount'])

        response = self.client.post(
            '/api/hotel-search/',
            search_criteria(),
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data'][0]['price'],
            {
                'currency': 'NGN',
                'grandTotal': '330000.00',
                'nightly': '55000.00',
            },
        )

    def test_local_destination_selection_does_not_require_coordinates(self):
        criteria = search_criteria()
        criteria.pop('city')
        criteria['destination'] = {
            'id': 'local-city-lagos',
            'type': 'city',
            'label': 'Lagos, Nigeria',
            'city': 'Lagos',
            'country': 'Nigeria',
        }

        response = self.client.post(
            '/api/hotel-search/',
            criteria,
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(response.data['data'][0]['property']['city'], 'Lagos')

    def test_search_filters_active_capacity_rooms_room_type_and_test_data(self):
        self.listing.active = False
        self.listing.save(update_fields=['active'])
        create_listing(name='Too few rooms', available_rooms=1)
        create_listing(name='Too little capacity', max_guests=1)
        create_listing(name='Wrong room type', room_type='Family Room')
        test_listing = create_listing(name='[TEST DATA] Hidden', test_data=True)

        response = self.client.post(
            '/api/hotel-search/',
            search_criteria(roomType='standard king'),
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], [])

        with self.settings(ALLOW_HOTEL_TEST_DATA=True):
            visible_response = self.client.post(
                '/api/hotel-search/',
                search_criteria(roomType='Standard King'),
                format='json',
            )
        self.assertEqual(visible_response.status_code, 200)
        self.assertEqual(
            [item['listingId'] for item in visible_response.data['data']],
            [test_listing.pk],
        )
        self.assertIs(visible_response.data['data'][0]['testData'], True)

    def test_invalid_searches_are_rejected_and_logged_as_failures(self):
        today = timezone.localdate()
        cases = (
            {'checkInDate': (today - timedelta(days=1)).isoformat()},
            {
                'checkInDate': today.isoformat(),
                'checkOutDate': today.isoformat(),
            },
            {
                'checkInDate': (today + timedelta(days=1)).isoformat(),
                'checkOutDate': (today + timedelta(days=101)).isoformat(),
            },
            {
                'checkInDate': (today + timedelta(days=331)).isoformat(),
                'checkOutDate': (today + timedelta(days=332)).isoformat(),
            },
            {'rooms': 0},
            {'guests': 0},
            {'rooms': 3, 'guests': 2},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                response = self.client.post(
                    '/api/hotel-search/',
                    search_criteria(**overrides),
                    format='json',
                )
                self.assertEqual(response.status_code, 400)

        failed_logs = TravelSearchLog.objects.filter(
            service_type=TravelSearchLog.SERVICE_HOTEL,
            status=TravelSearchLog.STATUS_FAILED,
            error_code='HOTEL_SEARCH_INVALID',
        )
        self.assertEqual(failed_logs.count(), len(cases))

    @override_settings(HOTEL_SEARCH_PROVIDER='unsupported')
    def test_unsupported_provider_is_explicit_and_logged(self):
        response = self.client.post(
            '/api/hotel-search/',
            search_criteria(),
            format='json',
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'HOTEL_SEARCH_NOT_CONFIGURED')
        search_log = TravelSearchLog.objects.get()
        self.assertEqual(search_log.status, TravelSearchLog.STATUS_FAILED)
        self.assertEqual(search_log.error_code, 'HOTEL_SEARCH_NOT_CONFIGURED')

    def test_public_search_is_throttled(self):
        cache.clear()
        with patch.object(
            ScopedRateThrottle,
            'THROTTLE_RATES',
            {'hotel_search': '1/minute'},
        ):
            first = self.client.post(
                '/api/hotel-search/',
                search_criteria(),
                format='json',
                REMOTE_ADDR='203.0.113.7',
            )
            second = self.client.post(
                '/api/hotel-search/',
                search_criteria(),
                format='json',
                REMOTE_ADDR='203.0.113.7',
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


@override_settings(
    HOTEL_SEARCH_PROVIDER='local',
    ALLOW_HOTEL_TEST_DATA=False,
)
class HotelBookingContractTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='hotel-customer',
            email='hotel@example.com',
            password='password123',
            first_name='Ada',
            last_name='Okafor',
        )
        self.listing = create_listing()
        TravelPricingSettings.objects.update_or_create(
            pk=1,
            defaults={
                'usd_to_ngn_rate': Decimal('1500.0000'),
                'flight_markup_percent': Decimal('0.00'),
                'hotel_markup_percent': Decimal('10.00'),
            },
        )
        self.client = APIClient()

    @patch('base.views.send_email')
    def test_structured_request_reprices_and_ignores_forged_snapshots(self, send_email):
        self.client.force_authenticate(user=self.user)
        criteria = search_criteria(rooms=1, guests=2)
        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'listingId': self.listing.pk,
                'criteria': criteria,
                'hotel_details': {'price': '0.01', 'name': 'Forged'},
                'search_results': {
                    'listingId': self.listing.pk,
                    'price': {'currency': 'NGN', 'grandTotal': '0.01'},
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        booking = HotelBooking.objects.get()
        self.assertEqual(booking.user, self.user)
        self.assertEqual(booking.listing, self.listing)
        self.assertEqual(
            booking.search_results['price'],
            {
                'currency': 'NGN',
                'grandTotal': '495000.00',
                'nightly': '165000.00',
            },
        )
        self.assertEqual(
            booking.hotel_details['property']['name'],
            self.listing.name,
        )
        self.assertNotIn('Forged', str(booking.hotel_details))
        self.assertEqual(booking.user_details['email'], self.user.email)
        self.assertEqual(response.data['listingId'], self.listing.pk)
        self.assertEqual(response.data['reference'], f'TTH-{booking.pk:06d}')
        self.assertIn('final price will be confirmed', response.data['message'])
        send_email.assert_called_once()

    def test_structured_hotel_request_requires_authentication(self):
        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'listingId': self.listing.pk,
                'criteria': search_criteria(rooms=1, guests=2),
            },
            format='json',
        )

        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(HotelBooking.objects.exists())

    def test_listing_is_revalidated_when_request_is_submitted(self):
        self.client.force_authenticate(user=self.user)
        self.listing.active = False
        self.listing.save(update_fields=['active'])

        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'listingId': self.listing.pk,
                'criteria': search_criteria(rooms=1, guests=2),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(HotelBooking.objects.exists())

    @patch('base.views.send_email')
    def test_legacy_authenticated_contract_remains_supported(self, send_email):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'user': {
                    'username': self.user.username,
                    'email': self.user.email,
                },
                'hotel_details': {
                    'city': 'Lagos',
                    'checkInDate': search_criteria()['checkInDate'],
                    'checkOutDate': search_criteria()['checkOutDate'],
                    'guests': 1,
                    'roomType': 'standard',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        booking = HotelBooking.objects.get()
        self.assertIsNone(booking.listing)
        self.assertEqual(booking.hotel_details['city'], 'Lagos')
        send_email.assert_called_once()


class TravelAdminHotelListingAPITests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='hotel-admin',
            email='admin@example.com',
            password='password123',
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username='hotel-member',
            email='member@example.com',
            password='password123',
        )
        self.listing = create_listing()
        self.client = APIClient()

    def test_hotel_inventory_endpoints_require_staff(self):
        anonymous_list = self.client.get('/api/travel-admin/hotels/')
        anonymous_detail = self.client.get(
            f'/api/travel-admin/hotels/{self.listing.pk}/'
        )
        self.client.force_authenticate(user=self.member)
        member_list = self.client.get('/api/travel-admin/hotels/')
        member_patch = self.client.patch(
            f'/api/travel-admin/hotels/{self.listing.pk}/',
            {'active': False},
            format='json',
        )

        self.assertIn(anonymous_list.status_code, (401, 403))
        self.assertIn(anonymous_detail.status_code, (401, 403))
        self.assertEqual(member_list.status_code, 403)
        self.assertEqual(member_patch.status_code, 403)

    def test_staff_can_list_create_and_patch_hotel_inventory(self):
        self.client.force_authenticate(user=self.staff)
        list_response = self.client.get(
            '/api/travel-admin/hotels/?page_size=1'
        )
        create_response = self.client.post(
            '/api/travel-admin/hotels/',
            {
                'name': '  Abuja   Central Hotel ',
                'city': ' Abuja ',
                'country': 'Nigeria',
                'address': '12 Test Avenue',
                'room_type': 'Deluxe Suite',
                'nightly_amount': '75000.00',
                'source_currency': 'NGN',
                'max_guests': 3,
                'star_rating': 4,
                'image_url': '',
                'amenities': [' Wi-Fi ', 'Breakfast'],
                'available_rooms': 6,
                'active': True,
                'test_data': False,
            },
            format='json',
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(len(list_response.data['results']), 1)
        self.assertEqual(create_response.status_code, 201)
        listing_id = create_response.data['id']
        self.assertEqual(create_response.data['name'], 'Abuja Central Hotel')
        self.assertEqual(create_response.data['city'], 'Abuja')
        self.assertEqual(create_response.data['amenities'], ['Wi-Fi', 'Breakfast'])

        patch_response = self.client.patch(
            f'/api/travel-admin/hotels/{listing_id}/',
            {'nightly_amount': '80000.00', 'active': False},
            format='json',
        )
        put_response = self.client.put(
            f'/api/travel-admin/hotels/{listing_id}/',
            {},
            format='json',
        )
        delete_response = self.client.delete(
            f'/api/travel-admin/hotels/{listing_id}/'
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data['nightly_amount'], '80000.00')
        self.assertIs(patch_response.data['active'], False)
        self.assertEqual(put_response.status_code, 405)
        self.assertEqual(delete_response.status_code, 405)

    def test_admin_validation_rejects_invalid_inventory(self):
        self.client.force_authenticate(user=self.staff)
        invalid_amenities = self.client.patch(
            f'/api/travel-admin/hotels/{self.listing.pk}/',
            {'amenities': {'wifi': True}},
            format='json',
        )
        invalid_price = self.client.patch(
            f'/api/travel-admin/hotels/{self.listing.pk}/',
            {'nightly_amount': '0.00'},
            format='json',
        )

        self.assertEqual(invalid_amenities.status_code, 400)
        self.assertEqual(invalid_price.status_code, 400)


class SeedTestHotelsCommandTests(TestCase):
    @override_settings(DEBUG=True, ALLOW_HOTEL_TEST_DATA=True)
    def test_seed_command_is_local_only_clear_and_idempotent(self):
        output = StringIO()
        call_command('seed_test_hotels', stdout=output)
        call_command('seed_test_hotels', stdout=output)

        listings = HotelListing.objects.filter(test_data=True)
        self.assertEqual(listings.count(), 3)
        self.assertTrue(
            all(item.name.startswith('[TEST DATA]') for item in listings)
        )
        self.assertIn('Seeded 3 test hotel listings', output.getvalue())

    @override_settings(DEBUG=False, ALLOW_HOTEL_TEST_DATA=False)
    def test_seed_command_refuses_non_qa_settings(self):
        with self.assertRaises(CommandError):
            call_command('seed_test_hotels')
