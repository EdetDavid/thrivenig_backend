import hashlib
import json
import logging
import socket
import ssl
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from urllib import error, parse, request

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.crypto import salted_hmac

from base.models import HotelListing

from .travel_pricing import TravelPricingError, apply_hotel_pricing


logger = logging.getLogger(__name__)
PROVIDER_NAME = 'Thrive inventory'
DUFFEL_PROVIDER_NAME = 'Duffel Stays'
AVAILABILITY_MESSAGE = 'Availability and final price will be confirmed.'
LIVE_AVAILABILITY_MESSAGE = (
    'Live price at search time; availability and final price must be rechecked '
    'before confirmation.'
)
HOTEL_SEARCH_PIPELINE_VERSION = 'duffel-stays-v1'
DUFFEL_TEST_HOTEL_LOCATION = {
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


class HotelSearchError(Exception):
    """Base exception for sanitized hotel supplier failures."""


class HotelSearchNotConfigured(HotelSearchError):
    pass


class HotelSearchTimeout(HotelSearchError):
    pass


class HotelSearchProviderError(HotelSearchError):
    pass


class HotelSearchValidationError(HotelSearchError):
    pass


class HotelSearchPermissionError(HotelSearchError):
    pass


class HotelListingUnavailable(ValueError):
    """Raised when a listing or cached live result is no longer available."""


def configured_provider():
    return str(settings.HOTEL_SEARCH_PROVIDER or '').strip().lower()


def provider_display_name():
    provider = configured_provider()
    if provider == 'duffel':
        return DUFFEL_PROVIDER_NAME
    if provider == 'local':
        return PROVIDER_NAME
    return provider or 'unconfigured'


def _provider_is_local():
    return configured_provider() == 'local'


def _is_duffel_test_token(access_token):
    return str(access_token or '').strip().lower().startswith('duffel_test_')


def _duffel_access_token():
    access_token = str(settings.DUFFEL_ACCESS_TOKEN or '').strip()
    if not access_token:
        raise HotelSearchNotConfigured(
            'Live hotel search has not been configured.'
        )
    if _is_duffel_test_token(access_token) and not settings.ALLOW_DUFFEL_TEST_DATA:
        raise HotelSearchPermissionError(
            'Duffel test hotel data is disabled for this environment.'
        )
    return access_token


def _ssl_context():
    context = ssl.create_default_context()
    if (
        settings.HOTEL_SEARCH_RELAX_TLS_STRICT
        and hasattr(ssl, 'VERIFY_X509_STRICT')
    ):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _duffel_headers(access_token, *, json_body=False):
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Duffel-Version': settings.DUFFEL_API_VERSION,
        'Accept': 'application/json',
    }
    if json_body:
        headers['Content-Type'] = 'application/json'
    return headers


def _perform_duffel_request(supplier_request, *, operation):
    try:
        with request.urlopen(
            supplier_request,
            timeout=settings.HOTEL_SEARCH_TIMEOUT_SECONDS,
            context=_ssl_context(),
        ) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (TimeoutError, socket.timeout) as exc:
        logger.warning('Duffel hotel %s timed out', operation)
        raise HotelSearchTimeout(
            'The hotel supplier took too long to respond.'
        ) from exc
    except error.HTTPError as exc:
        request_id = (
            exc.headers.get('x-request-id') if exc.headers is not None else None
        )
        logger.warning(
            'Duffel hotel %s returned HTTP %s (request_id=%s)',
            operation,
            exc.code,
            request_id or 'unknown',
        )
        if exc.code in {400, 422}:
            raise HotelSearchValidationError(
                'One or more hotel search details were not accepted.'
            ) from exc
        if exc.code in {401, 403}:
            raise HotelSearchPermissionError(
                'Duffel Stays access is required for the configured account.'
            ) from exc
        if exc.code == 429:
            raise HotelSearchProviderError(
                'The hotel supplier is busy. Please try again shortly.'
            ) from exc
        raise HotelSearchProviderError(
            'Live hotel search is temporarily unavailable.'
        ) from exc
    except error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            logger.warning('Duffel hotel %s timed out', operation)
            raise HotelSearchTimeout(
                'The hotel supplier took too long to respond.'
            ) from exc
        logger.warning('Duffel hotel %s request failed', operation)
        raise HotelSearchProviderError(
            'Live hotel search is temporarily unavailable.'
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning('Duffel hotel %s returned malformed JSON', operation)
        raise HotelSearchProviderError(
            'The hotel supplier returned an invalid response.'
        ) from exc

    if not isinstance(payload, dict):
        raise HotelSearchProviderError(
            'The hotel supplier returned an invalid response.'
        )
    return payload


def _listing_is_allowed(listing, criteria):
    room_type = str(criteria.get('roomType') or '').strip()
    rooms = int(criteria['rooms'])
    guests = int(criteria['guests'])

    if not listing.active:
        return False
    if listing.test_data and not settings.ALLOW_HOTEL_TEST_DATA:
        return False
    if listing.city.casefold() != str(criteria['city']).strip().casefold():
        return False
    if room_type and listing.room_type.casefold() != room_type.casefold():
        return False
    if listing.available_rooms < rooms:
        return False
    return listing.max_guests * rooms >= guests


def _source_offer(listing, criteria):
    nights = (criteria['checkOutDate'] - criteria['checkInDate']).days
    rooms = int(criteria['rooms'])
    total = listing.nightly_amount * Decimal(nights * rooms)
    amenities = (
        [item for item in listing.amenities if isinstance(item, str)]
        if isinstance(listing.amenities, list)
        else []
    )
    checked_at = timezone.now().isoformat()

    return {
        'id': f'hotel-{listing.pk}',
        'searchResultId': f'local-hotel-{listing.pk}',
        'listingId': listing.pk,
        'provider': PROVIDER_NAME,
        'source': 'local',
        'liveMode': False,
        'testData': listing.test_data,
        'expiresAt': None,
        'checkedAt': checked_at,
        'property': {
            'name': listing.name,
            'city': listing.city,
            'country': listing.country,
            'address': listing.address,
            'starRating': listing.star_rating,
            'imageUrl': listing.image_url,
            'amenities': amenities,
        },
        'room': {
            'type': listing.room_type,
            'maxGuests': listing.max_guests,
            'availableRooms': listing.available_rooms,
        },
        'stay': {
            'checkInDate': criteria['checkInDate'].isoformat(),
            'checkOutDate': criteria['checkOutDate'].isoformat(),
            'nights': nights,
            'rooms': rooms,
            'guests': int(criteria['guests']),
            'adults': int(criteria['adults']),
            'childAges': list(criteria['childAges']),
        },
        'price': {
            'currency': listing.source_currency,
            'grandTotal': str(total),
            'base': str(listing.nightly_amount),
        },
        'availability': {
            'status': 'on_request',
            'message': AVAILABILITY_MESSAGE,
        },
    }


def _format_priced_results(results):
    priced = apply_hotel_pricing(results)
    data = []
    for offer in priced['data']:
        # Supplier resource IDs are retained only in the server-side cache.
        offer.pop('_providerResultId', None)
        price = offer['price']
        offer['price'] = {
            'currency': price['currency'],
            'grandTotal': price['grandTotal'],
            'nightly': price.get('base') or price['grandTotal'],
        }
        data.append(offer)
    data.sort(key=lambda item: (Decimal(item['price']['grandTotal']), item['id']))
    priced['data'] = data
    return priced


def _price_listings(listings, criteria):
    source_results = {
        'data': [_source_offer(listing, criteria) for listing in listings],
        'meta': {
            'provider': PROVIDER_NAME,
            'live': False,
            'testData': any(listing.test_data for listing in listings),
            'checkedAt': timezone.now().isoformat(),
        },
    }
    return _format_priced_results(source_results)


def _guest_payload(criteria):
    guests = [{'type': 'adult'} for _ in range(int(criteria['adults']))]
    guests.extend(
        {'type': 'child', 'age': int(age)} for age in criteria['childAges']
    )
    return guests


def build_duffel_stays_request(criteria):
    destination = criteria['destination']
    return {
        'data': {
            'location': {
                'radius': int(criteria['radiusKm']),
                'geographic_coordinates': {
                    'latitude': float(destination['latitude']),
                    'longitude': float(destination['longitude']),
                },
            },
            'check_in_date': criteria['checkInDate'].isoformat(),
            'check_out_date': criteria['checkOutDate'].isoformat(),
            'rooms': int(criteria['rooms']),
            'guests': _guest_payload(criteria),
            'free_cancellation_only': bool(criteria['freeCancellationOnly']),
        }
    }


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _first_photo(accommodation):
    for photo in accommodation.get('photos') or []:
        if isinstance(photo, dict) and _text(photo.get('url')):
            return _text(photo['url'])
    return ''


def _amenities(accommodation):
    values = []
    for amenity in accommodation.get('amenities') or []:
        if not isinstance(amenity, dict):
            continue
        label = _text(amenity.get('description')) or _text(amenity.get('type'))
        if label and label not in values:
            values.append(label)
    return values


def _address_text(address):
    if not isinstance(address, dict):
        return ''
    values = [
        _text(address.get('line_one')),
        _text(address.get('city_name')),
        _text(address.get('region')),
        _text(address.get('postal_code')),
        _text(address.get('country_code')).upper(),
    ]
    return ', '.join(value for value in values if value)


def _nightly_source_amount(total_amount, nights, rooms):
    try:
        total = Decimal(str(total_amount))
    except (InvalidOperation, TypeError, ValueError):
        return total_amount
    divisor = Decimal(max(1, nights * rooms))
    return str(total / divisor)


def _room_summary(accommodation, guest_count):
    room_items = accommodation.get('rooms')
    if not isinstance(room_items, list):
        room_items = []
    first_room = next((room for room in room_items if isinstance(room, dict)), {})
    available = []
    for room in room_items:
        if not isinstance(room, dict):
            continue
        for rate in room.get('rates') or []:
            if isinstance(rate, dict) and isinstance(rate.get('quantity_available'), int):
                available.append(rate['quantity_available'])
    return {
        'type': _text(first_room.get('name')) or 'Cheapest available room',
        'maxGuests': guest_count,
        'availableRooms': min(available) if available else None,
    }


def _public_search_result_id(provider_result_id, checked_at):
    digest = salted_hmac(
        'hotel-live-search-result',
        f'{provider_result_id}|{checked_at}',
    ).hexdigest()
    return f'hsr_{digest[:40]}'


def normalize_duffel_stays_response(payload, criteria, *, test_data):
    container = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(container, dict) or not isinstance(container.get('results'), list):
        raise HotelSearchProviderError(
            'The hotel supplier returned an invalid response.'
        )

    checked_at = _text(container.get('created_at')) or timezone.now().isoformat()
    nights = (criteria['checkOutDate'] - criteria['checkInDate']).days
    rooms = int(criteria['rooms'])
    guest_count = int(criteria['guests'])
    normalized = []
    for result in container['results'][: settings.HOTEL_SEARCH_RESULT_LIMIT]:
        if not isinstance(result, dict):
            continue
        search_result_id = _text(result.get('id'))
        accommodation = result.get('accommodation')
        if not search_result_id or not isinstance(accommodation, dict):
            continue
        total_amount = result.get('cheapest_rate_total_amount')
        currency = _text(result.get('cheapest_rate_currency')).upper()
        if total_amount in (None, '') or len(currency) != 3:
            continue
        location = accommodation.get('location')
        if not isinstance(location, dict):
            location = {}
        address = location.get('address')
        if not isinstance(address, dict):
            address = {}
        destination = criteria['destination']
        city = _text(address.get('city_name')) or destination['city']
        country_code = _text(address.get('country_code')).upper()
        country = destination.get('country') or country_code
        expires_at = _text(result.get('expires_at')) or None
        public_result_id = _public_search_result_id(
            search_result_id,
            checked_at,
        )

        normalized.append(
            {
                'id': public_result_id,
                'searchResultId': public_result_id,
                '_providerResultId': search_result_id,
                'listingId': None,
                'provider': DUFFEL_PROVIDER_NAME,
                'source': 'duffel',
                'liveMode': not test_data,
                'testData': test_data,
                'expiresAt': expires_at,
                'checkedAt': checked_at,
                'property': {
                    'name': _text(accommodation.get('name')) or 'Hotel',
                    'city': city,
                    'country': country,
                    'address': _address_text(address),
                    'starRating': accommodation.get('rating'),
                    'imageUrl': _first_photo(accommodation),
                    'amenities': _amenities(accommodation),
                },
                'room': _room_summary(accommodation, guest_count),
                'stay': {
                    'checkInDate': _text(result.get('check_in_date'))
                    or criteria['checkInDate'].isoformat(),
                    'checkOutDate': _text(result.get('check_out_date'))
                    or criteria['checkOutDate'].isoformat(),
                    'nights': nights,
                    'rooms': int(result.get('rooms') or rooms),
                    'guests': guest_count,
                    'adults': int(criteria['adults']),
                    'childAges': list(criteria['childAges']),
                },
                'price': {
                    'currency': currency,
                    'grandTotal': str(total_amount),
                    'base': _nightly_source_amount(total_amount, nights, rooms),
                },
                'availability': {
                    'status': 'available',
                    'message': LIVE_AVAILABILITY_MESSAGE,
                },
            }
        )

    return {
        'data': normalized,
        'meta': {
            'provider': DUFFEL_PROVIDER_NAME,
            'live': not test_data,
            'testData': test_data,
            'checkedAt': checked_at,
            'resultLimit': settings.HOTEL_SEARCH_RESULT_LIMIT,
            'returnedResultCount': len(normalized),
        },
    }


def _search_duffel(criteria):
    access_token = _duffel_access_token()
    supplier_request = request.Request(
        f"{settings.DUFFEL_API_BASE_URL.rstrip('/')}/stays/search",
        data=json.dumps(build_duffel_stays_request(criteria)).encode('utf-8'),
        headers=_duffel_headers(access_token, json_body=True),
        method='POST',
    )
    payload = _perform_duffel_request(supplier_request, operation='search')
    try:
        return normalize_duffel_stays_response(
            payload,
            criteria,
            test_data=_is_duffel_test_token(access_token),
        )
    except HotelSearchProviderError:
        raise
    except (AttributeError, InvalidOperation, TypeError, ValueError) as exc:
        logger.warning('Duffel hotel search returned malformed result data')
        raise HotelSearchProviderError(
            'The hotel supplier returned an invalid response.'
        ) from exc


def _configuration_digest(provider):
    values = [
        provider,
        str(settings.DUFFEL_ACCESS_TOKEN),
        str(settings.DUFFEL_API_BASE_URL),
        str(settings.DUFFEL_API_VERSION),
        str(settings.ALLOW_DUFFEL_TEST_DATA),
        str(settings.ALLOW_HOTEL_TEST_DATA),
        str(settings.HOTEL_SEARCH_RESULT_LIMIT),
        HOTEL_SEARCH_PIPELINE_VERSION,
    ]
    return hashlib.sha256('|'.join(values).encode('utf-8')).hexdigest()[:16]


def _criteria_json(criteria):
    return {
        key: (
            value.isoformat()
            if hasattr(value, 'isoformat')
            else value
        )
        for key, value in criteria.items()
    }


def _search_cache_key(provider, criteria):
    serialized = json.dumps(
        _criteria_json(criteria),
        sort_keys=True,
        separators=(',', ':'),
    )
    criteria_digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f'hotel-search:{_configuration_digest(provider)}:{criteria_digest}'


def _result_cache_key(provider, search_result_id):
    result_digest = hashlib.sha256(
        str(search_result_id).encode('utf-8')
    ).hexdigest()
    return f'hotel-result:{_configuration_digest(provider)}:{result_digest}'


def _expiry_datetime(expires_at):
    expires = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime_timezone.utc)
    return expires


def _result_timeout(expires_at):
    timeout = int(settings.HOTEL_SEARCH_CACHE_SECONDS)
    if not expires_at:
        return timeout
    try:
        expires = _expiry_datetime(expires_at)
        remaining = int((expires - timezone.now()).total_seconds())
    except (TypeError, ValueError):
        return timeout
    return max(1, min(timeout, remaining))


def _store_result_snapshots(results, criteria):
    provider = configured_provider()
    for result in results.get('data', []):
        if not isinstance(result, dict) or not result.get('searchResultId'):
            continue
        cache.set(
            _result_cache_key(provider, result['searchResultId']),
            {
                'criteria': _criteria_json(criteria),
                'result': result,
                'meta': results.get('meta', {}),
            },
            timeout=_result_timeout(result.get('expiresAt')),
        )


def _search_local(criteria):
    queryset = HotelListing.objects.filter(
        active=True,
        city__iexact=criteria['city'],
        available_rooms__gte=criteria['rooms'],
    )
    room_type = str(criteria.get('roomType') or '').strip()
    if room_type:
        queryset = queryset.filter(room_type__iexact=room_type)
    if not settings.ALLOW_HOTEL_TEST_DATA:
        queryset = queryset.filter(test_data=False)
    listings = [
        listing
        for listing in queryset
        if listing.max_guests * int(criteria['rooms']) >= int(criteria['guests'])
    ]
    return {
        'data': [_source_offer(listing, criteria) for listing in listings],
        'meta': {
            'provider': PROVIDER_NAME,
            'live': False,
            'testData': any(listing.test_data for listing in listings),
            'checkedAt': timezone.now().isoformat(),
        },
    }


def search_hotels(criteria):
    """Return provider-neutral live or curated hotel search results."""

    provider = configured_provider()
    if not provider:
        raise HotelSearchNotConfigured('Hotel search has not been configured.')
    cache_key = _search_cache_key(provider, criteria)
    results = cache.get(cache_key)
    if results is None:
        if provider == 'local':
            results = _search_local(criteria)
        elif provider == 'duffel':
            results = _search_duffel(criteria)
        else:
            raise HotelSearchNotConfigured(
                'The configured hotel search provider is not supported.'
            )
        cache_timeout = settings.HOTEL_SEARCH_CACHE_SECONDS
        if not results.get('data'):
            cache_timeout = min(cache_timeout, 30)
        cache.set(cache_key, results, timeout=cache_timeout)

    if results.get('meta', {}).get('testData'):
        if provider == 'duffel' and not settings.ALLOW_DUFFEL_TEST_DATA:
            cache.delete(cache_key)
            raise HotelSearchPermissionError(
                'Duffel test hotel data is disabled for this environment.'
            )
        if provider == 'local' and not settings.ALLOW_HOTEL_TEST_DATA:
            cache.delete(cache_key)
            results = _search_local(criteria)

    _store_result_snapshots(results, criteria)
    return _format_priced_results(results)


def resolve_hotel_listing(listing, criteria):
    """Revalidate and reprice one curated listing for a hotel request."""

    if not _provider_is_local():
        raise HotelSearchNotConfigured(
            'Hotel search is not configured for the local inventory provider.'
        )
    if not _listing_is_allowed(listing, criteria):
        raise HotelListingUnavailable(
            'This hotel listing is not available for the requested criteria.'
        )
    return _price_listings([listing], criteria)['data'][0]


def resolve_hotel_search_result(search_result_id, criteria):
    """Resolve a live booking request from the server-side cached snapshot."""

    provider = configured_provider()
    cached = cache.get(_result_cache_key(provider, search_result_id))
    if not isinstance(cached, dict) or not isinstance(cached.get('result'), dict):
        raise HotelListingUnavailable(
            'This hotel result has expired. Please run a new search.'
        )
    if cached.get('criteria') != _criteria_json(criteria):
        raise HotelListingUnavailable(
            'This hotel result does not match the requested stay.'
        )
    result = cached['result']
    expires_at = result.get('expiresAt')
    if expires_at:
        try:
            expires = _expiry_datetime(expires_at)
        except (TypeError, ValueError) as exc:
            raise HotelListingUnavailable(
                'This hotel result has invalid availability data.'
            ) from exc
        if expires <= timezone.now():
            cache.delete(_result_cache_key(provider, search_result_id))
            raise HotelListingUnavailable(
                'This hotel result has expired. Please run a new search.'
            )
    try:
        return _format_priced_results(
            {'data': [result], 'meta': cached.get('meta', {})}
        )['data'][0]
    except TravelPricingError as exc:
        raise HotelListingUnavailable(
            'This hotel price is temporarily unavailable.'
        ) from exc


def _coordinates(place):
    latitude = place.get('latitude')
    longitude = place.get('longitude')
    if latitude is not None and longitude is not None:
        return latitude, longitude
    airports = place.get('airports')
    if not isinstance(airports, list):
        return None, None
    points = [
        (airport.get('latitude'), airport.get('longitude'))
        for airport in airports
        if isinstance(airport, dict)
        and airport.get('latitude') is not None
        and airport.get('longitude') is not None
    ]
    if not points:
        return None, None
    return (
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    )


def normalize_duffel_hotel_locations(payload):
    places = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(places, list):
        raise HotelSearchProviderError(
            'The hotel location supplier returned an invalid response.'
        )
    normalized = []
    for place in places:
        if not isinstance(place, dict):
            continue
        place_type = _text(place.get('type')).lower()
        place_id = _text(place.get('id'))
        name = _text(place.get('name'))
        if place_type not in {'city', 'airport'} or not place_id or not name:
            continue
        city = place.get('city') if isinstance(place.get('city'), dict) else {}
        city_name = _text(place.get('city_name')) or _text(city.get('name'))
        if place_type == 'city':
            city_name = city_name or name
        country_code = _text(place.get('iata_country_code')).upper()
        latitude, longitude = _coordinates(place)
        if latitude is None or longitude is None:
            continue
        display_name = city_name if place_type == 'airport' and city_name else name
        normalized.append(
            {
                'id': place_id,
                'type': place_type,
                'iataCode': _text(place.get('iata_code')).upper() or None,
                'name': name,
                'cityName': city_name or None,
                'countryCode': country_code or None,
                'latitude': latitude,
                'longitude': longitude,
                'label': ', '.join(
                    value for value in [display_name, country_code] if value
                ),
            }
        )
    return {'data': normalized}


def _search_duffel_locations(query):
    access_token = _duffel_access_token()
    url = (
        f"{settings.DUFFEL_API_BASE_URL.rstrip('/')}/places/suggestions?"
        f"{parse.urlencode({'query': query})}"
    )
    supplier_request = request.Request(
        url,
        headers=_duffel_headers(access_token),
        method='GET',
    )
    payload = _perform_duffel_request(supplier_request, operation='location search')
    try:
        return normalize_duffel_hotel_locations(payload)
    except HotelSearchProviderError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning('Duffel hotel location search returned malformed data')
        raise HotelSearchProviderError(
            'The hotel location supplier returned an invalid response.'
        ) from exc


def _search_local_locations(query):
    listings = HotelListing.objects.filter(
        active=True,
        city__icontains=query,
    ).order_by('city', 'country')
    if not settings.ALLOW_HOTEL_TEST_DATA:
        listings = listings.filter(test_data=False)
    seen = set()
    results = []
    for listing in listings:
        key = (listing.city.casefold(), listing.country.casefold())
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                'id': f'local-city-{hashlib.sha256("|".join(key).encode()).hexdigest()[:16]}',
                'type': 'city',
                'iataCode': None,
                'name': listing.city,
                'cityName': listing.city,
                'countryCode': None,
                'latitude': None,
                'longitude': None,
                'label': f'{listing.city}, {listing.country}',
            }
        )
    return {'data': results}


def search_hotel_locations(query):
    provider = configured_provider()
    normalized_query = ' '.join(str(query).split()).casefold()
    if (
        provider == 'duffel'
        and _is_duffel_test_token(_duffel_access_token())
        and settings.ALLOW_DUFFEL_TEST_DATA
        and (
            ('duffel' in normalized_query and 'test' in normalized_query)
            or normalized_query in {'test hotel', 'test hotels'}
        )
    ):
        return {'data': [dict(DUFFEL_TEST_HOTEL_LOCATION)]}
    query_digest = hashlib.sha256(normalized_query.encode('utf-8')).hexdigest()
    cache_key = (
        f'hotel-locations:{_configuration_digest(provider)}:{query_digest}'
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    if provider == 'local':
        results = _search_local_locations(normalized_query)
    elif provider == 'duffel':
        results = _search_duffel_locations(normalized_query)
    else:
        raise HotelSearchNotConfigured(
            'The configured hotel location provider is not supported.'
        )
    cache.set(cache_key, results, timeout=settings.HOTEL_LOCATION_CACHE_SECONDS)
    return results
