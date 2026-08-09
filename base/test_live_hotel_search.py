import json
import ssl
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import HotelBooking, TravelPricingSettings, TravelSearchLog
from .services.fx_rates import get_usd_rate
from .services.hotel_search import (
    HotelSearchPermissionError,
    HotelSearchProviderError,
    HotelSearchTimeout,
    HotelSearchValidationError,
    _ssl_context,
)


def live_criteria(**overrides):
    check_in = timezone.localdate() + timedelta(days=30)
    values = {
        'destination': {
            'id': 'cit_lon_gb',
            'label': 'London, United Kingdom',
            'city': 'London',
            'country': 'United Kingdom',
            'countryCode': 'GB',
            'latitude': 51.5071,
            'longitude': -0.1416,
        },
        'checkInDate': check_in.isoformat(),
        'checkOutDate': (check_in + timedelta(days=2)).isoformat(),
        'rooms': 1,
        'adults': 2,
        'childAges': [7],
        'radiusKm': 8,
        'freeCancellationOnly': True,
    }
    values.update(overrides)
    return values


def duffel_search_fixture():
    criteria = live_criteria()
    return {
        'data': {
            'created_at': '2026-08-09T12:00:00Z',
            'results': [
                {
                    'id': 'srr_live_result',
                    'rooms': 1,
                    'expires_at': '2099-08-09T13:00:00Z',
                    'check_in_date': criteria['checkInDate'],
                    'check_out_date': criteria['checkOutDate'],
                    'cheapest_rate_total_amount': '100.00',
                    'cheapest_rate_currency': 'GBP',
                    'accommodation': {
                        'id': 'acc_london',
                        'name': 'Duffel Test Hotel',
                        'rating': 4,
                        'photos': [{'url': 'https://images.example/hotel.jpg'}],
                        'amenities': [
                            {'type': 'wifi', 'description': 'Wi-Fi'},
                            {'type': 'parking', 'description': 'Parking'},
                        ],
                        'location': {
                            'address': {
                                'line_one': '1 Test Street',
                                'city_name': 'London',
                                'region': 'England',
                                'postal_code': 'SW1A 1AA',
                                'country_code': 'GB',
                            }
                        },
                        'rooms': [
                            {
                                'name': 'Deluxe King',
                                'rates': [{'quantity_available': 3}],
                            }
                        ],
                    },
                }
            ],
        }
    }


@override_settings(
    HOTEL_SEARCH_PROVIDER='duffel',
    DUFFEL_ACCESS_TOKEN='duffel_test_server-only-token',
    DUFFEL_API_BASE_URL='https://api.duffel.com',
    DUFFEL_API_VERSION='v2',
    ALLOW_DUFFEL_TEST_DATA=True,
    HOTEL_SEARCH_TIMEOUT_SECONDS=30,
    HOTEL_SEARCH_CACHE_SECONDS=300,
    HOTEL_SEARCH_RESULT_LIMIT=50,
    HOTEL_LOCATION_CACHE_SECONDS=3600,
    HOTEL_SEARCH_DEFAULT_RADIUS_KM=10,
    HOTEL_FX_API_BASE_URL='https://api.frankfurter.dev/v2',
    HOTEL_FX_TIMEOUT_SECONDS=5,
    HOTEL_FX_CACHE_SECONDS=86400,
)
class DuffelHotelSearchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        TravelPricingSettings.objects.update_or_create(
            pk=1,
            defaults={
                'usd_to_ngn_rate': Decimal('1500.0000'),
                'flight_markup_percent': Decimal('0.00'),
                'hotel_markup_percent': Decimal('10.00'),
            },
        )

    @patch('base.services.fx_rates.urlopen')
    @patch('base.services.hotel_search.request.urlopen')
    def test_live_search_is_normalized_priced_cached_and_server_side(
        self,
        hotel_urlopen,
        fx_urlopen,
    ):
        hotel_response = MagicMock()
        hotel_response.read.return_value = json.dumps(
            duffel_search_fixture()
        ).encode('utf-8')
        hotel_urlopen.return_value.__enter__.return_value = hotel_response
        fx_response = MagicMock()
        fx_response.read.return_value = json.dumps(
            {'date': '2026-08-08', 'base': 'GBP', 'quote': 'USD', 'rate': 1.25}
        ).encode('utf-8')
        fx_urlopen.return_value.__enter__.return_value = fx_response

        first = self.client.post('/api/hotel-search/', live_criteria(), format='json')
        second = self.client.post('/api/hotel-search/', live_criteria(), format='json')

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(hotel_urlopen.call_count, 1)
        self.assertEqual(fx_urlopen.call_count, 1)
        supplier_request = hotel_urlopen.call_args.args[0]
        self.assertEqual(supplier_request.full_url, 'https://api.duffel.com/stays/search')
        self.assertEqual(supplier_request.get_method(), 'POST')
        self.assertEqual(
            supplier_request.get_header('Authorization'),
            'Bearer duffel_test_server-only-token',
        )
        self.assertEqual(supplier_request.get_header('Duffel-version'), 'v2')
        request_body = json.loads(supplier_request.data.decode('utf-8'))['data']
        self.assertEqual(request_body['location']['radius'], 8)
        self.assertEqual(
            request_body['location']['geographic_coordinates'],
            {'latitude': 51.5071, 'longitude': -0.1416},
        )
        self.assertEqual(
            request_body['guests'],
            [
                {'type': 'adult'},
                {'type': 'adult'},
                {'type': 'child', 'age': 7},
            ],
        )
        self.assertIs(request_body['free_cancellation_only'], True)

        result = first.data['data'][0]
        self.assertTrue(result['searchResultId'].startswith('hsr_'))
        self.assertNotEqual(result['searchResultId'], 'srr_live_result')
        self.assertNotIn('srr_live_result', json.dumps(first.data))
        self.assertIsNone(result['listingId'])
        self.assertEqual(result['source'], 'duffel')
        self.assertIs(result['liveMode'], False)
        self.assertIs(result['testData'], True)
        self.assertEqual(result['property']['name'], 'Duffel Test Hotel')
        self.assertEqual(result['room']['type'], 'Deluxe King')
        self.assertEqual(
            result['price'],
            {
                'currency': 'NGN',
                'grandTotal': '206250.00',
                'nightly': '103125.00',
            },
        )
        self.assertNotIn('duffel_test_server-only-token', json.dumps(first.data))
        log = TravelSearchLog.objects.filter(
            service_type=TravelSearchLog.SERVICE_HOTEL
        ).first()
        self.assertEqual(log.provider, 'Duffel Stays')
        self.assertEqual(log.display_currency, 'NGN')

    @patch('base.services.hotel_search.request.urlopen')
    def test_hotel_locations_have_coordinates_and_are_cached(self, urlopen):
        supplier_response = MagicMock()
        supplier_response.read.return_value = json.dumps(
            {
                'data': [
                    {
                        'id': 'cit_lon_gb',
                        'type': 'city',
                        'iata_code': 'lon',
                        'name': 'London',
                        'iata_country_code': 'gb',
                        'airports': [
                            {'latitude': 51.47, 'longitude': -0.45},
                            {'latitude': 51.15, 'longitude': -0.18},
                        ],
                    },
                    {
                        'id': 'arp_lhr_gb',
                        'type': 'airport',
                        'iata_code': 'lhr',
                        'name': 'Heathrow',
                        'city_name': 'London',
                        'iata_country_code': 'gb',
                        'latitude': 51.47,
                        'longitude': -0.45,
                    },
                ]
            }
        ).encode('utf-8')
        urlopen.return_value.__enter__.return_value = supplier_response

        first = self.client.get('/api/hotel-locations/', {'query': ' London '})
        second = self.client.get('/api/hotel-locations/', {'query': 'london'})

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.data, first.data)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(first.data['data'][0]['type'], 'city')
        self.assertAlmostEqual(first.data['data'][0]['latitude'], 51.31)
        self.assertAlmostEqual(first.data['data'][0]['longitude'], -0.315)
        self.assertEqual(first.data['data'][0]['label'], 'London, GB')
        self.assertEqual(first.data['data'][1]['cityName'], 'London')

    @patch('base.services.hotel_search.request.urlopen')
    def test_test_hotel_destination_uses_official_synthetic_coordinates(
        self,
        urlopen,
    ):
        response = self.client.get(
            '/api/hotel-locations/',
            {'query': 'Duffel test hotels'},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data['data'],
            [
                {
                    'id': 'duffel-test-hotels',
                    'type': 'city',
                    'iataCode': None,
                    'name': 'Duffel Test Hotels',
                    'cityName': 'Duffel Test Hotels',
                    'countryCode': None,
                    'latitude': -24.38,
                    'longitude': -128.32,
                    'label': 'Duffel Test Hotels (synthetic test data)',
                }
            ],
        )
        urlopen.assert_not_called()

    @override_settings(ALLOW_DUFFEL_TEST_DATA=False)
    @patch('base.services.hotel_search.request.urlopen')
    def test_test_token_is_blocked_before_network_access(self, urlopen):
        response = self.client.post(
            '/api/hotel-search/',
            live_criteria(),
            format='json',
        )

        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data['code'], 'HOTEL_SEARCH_PERMISSION_ERROR')
        urlopen.assert_not_called()
        log = TravelSearchLog.objects.get()
        self.assertEqual(log.error_code, 'HOTEL_SEARCH_PERMISSION_ERROR')

    def test_live_search_requires_coordinates_and_one_adult_per_room(self):
        missing_destination = self.client.post(
            '/api/hotel-search/',
            {
                **live_criteria(),
                'destination': None,
                'city': 'London',
            },
            format='json',
        )
        too_few_adults = self.client.post(
            '/api/hotel-search/',
            live_criteria(rooms=2, adults=1),
            format='json',
        )

        self.assertEqual(missing_destination.status_code, 400)
        self.assertIn('destination', missing_destination.data)
        self.assertEqual(too_few_adults.status_code, 400)
        self.assertIn('adults', too_few_adults.data)

    def test_supplier_error_classes_have_explicit_http_contracts(self):
        cases = (
            (
                HotelSearchTimeout('The hotel supplier took too long.'),
                504,
                'HOTEL_SEARCH_TIMEOUT',
            ),
            (
                HotelSearchValidationError('Search details were rejected.'),
                400,
                'HOTEL_SEARCH_INVALID',
            ),
            (
                HotelSearchPermissionError('Duffel Stays access is required.'),
                503,
                'HOTEL_SEARCH_PERMISSION_ERROR',
            ),
            (
                HotelSearchProviderError('Supplier unavailable.'),
                502,
                'HOTEL_SEARCH_PROVIDER_ERROR',
            ),
        )

        for exception, expected_status, expected_code in cases:
            with self.subTest(expected_code=expected_code), patch(
                'base.views.search_hotels',
                side_effect=exception,
            ):
                response = self.client.post(
                    '/api/hotel-search/',
                    live_criteria(),
                    format='json',
                )
            self.assertEqual(response.status_code, expected_status, response.data)
            self.assertEqual(response.data['code'], expected_code)

        self.assertEqual(
            list(
                TravelSearchLog.objects.order_by('id').values_list(
                    'error_code',
                    flat=True,
                )
            ),
            [case[2] for case in cases],
        )

    @override_settings(
        FLIGHT_SEARCH_RELAX_TLS_STRICT=True,
        HOTEL_SEARCH_RELAX_TLS_STRICT=False,
    )
    @patch('base.services.hotel_search.ssl.create_default_context')
    def test_flight_tls_workaround_does_not_relax_hotel_tls(self, create_context):
        context = MagicMock()
        context.verify_flags = getattr(ssl, 'VERIFY_X509_STRICT', 0) | 2
        create_context.return_value = context

        result = _ssl_context()

        self.assertIs(result, context)
        self.assertEqual(
            context.verify_flags,
            getattr(ssl, 'VERIFY_X509_STRICT', 0) | 2,
        )

    @patch('base.views.send_email')
    @patch('base.services.fx_rates.urlopen')
    @patch('base.services.hotel_search.request.urlopen')
    def test_authenticated_request_resolves_cached_result_and_reprices_it(
        self,
        hotel_urlopen,
        fx_urlopen,
        send_email,
    ):
        hotel_response = MagicMock()
        hotel_response.read.return_value = json.dumps(
            duffel_search_fixture()
        ).encode('utf-8')
        hotel_urlopen.return_value.__enter__.return_value = hotel_response
        fx_response = MagicMock()
        fx_response.read.return_value = json.dumps(
            {'date': '2026-08-08', 'base': 'GBP', 'quote': 'USD', 'rate': 1.25}
        ).encode('utf-8')
        fx_urlopen.return_value.__enter__.return_value = fx_response
        search = self.client.post('/api/hotel-search/', live_criteria(), format='json')
        self.assertEqual(search.status_code, 200, search.data)

        pricing = TravelPricingSettings.load()
        pricing.hotel_markup_percent = Decimal('20.00')
        pricing.save(update_fields=['hotel_markup_percent', 'updated_at'])
        user = User.objects.create_user(
            username='live-hotel-user',
            email='live-hotel@example.com',
            password='password123',
        )
        self.client.force_authenticate(user=user)
        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'searchResultId': search.data['data'][0]['searchResultId'],
                'criteria': live_criteria(),
                'hotel_details': {'name': 'Forged', 'price': '0.01'},
                'search_results': {'price': {'grandTotal': '0.01'}},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = HotelBooking.objects.get()
        self.assertIsNone(booking.listing)
        self.assertEqual(booking.search_results['price']['grandTotal'], '225000.00')
        self.assertEqual(
            booking.hotel_details['searchResultId'],
            search.data['data'][0]['searchResultId'],
        )
        self.assertNotIn('srr_live_result', str(booking.search_results))
        self.assertNotIn('Forged', str(booking.hotel_details))
        send_email.assert_called_once()

    def test_unknown_cached_result_is_rejected(self):
        user = User.objects.create_user(
            username='no-result-user',
            email='no-result@example.com',
            password='password123',
        )
        self.client.force_authenticate(user=user)
        response = self.client.post(
            '/api/hotel-bookings/',
            {
                'searchResultId': 'srr_not_in_server_cache',
                'criteria': live_criteria(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('searchResultId', response.data)
        self.assertFalse(HotelBooking.objects.exists())


@override_settings(
    HOTEL_FX_API_BASE_URL='https://api.frankfurter.dev/v2',
    HOTEL_FX_TIMEOUT_SECONDS=5,
    HOTEL_FX_CACHE_SECONDS=86400,
)
class HotelFxRateTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch('base.services.fx_rates.urlopen')
    def test_frankfurter_rate_is_validated_and_cached(self, urlopen):
        supplier_response = MagicMock()
        supplier_response.read.return_value = json.dumps(
            {'date': '2026-08-08', 'base': 'EUR', 'quote': 'USD', 'rate': 1.15}
        ).encode('utf-8')
        urlopen.return_value.__enter__.return_value = supplier_response

        first = get_usd_rate('eur')
        second = get_usd_rate('EUR')

        self.assertEqual(first, Decimal('1.15'))
        self.assertEqual(second, first)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            'https://api.frankfurter.dev/v2/rate/EUR/USD',
        )
