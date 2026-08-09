import hashlib
import json
import logging
import socket
import ssl
from urllib import error, parse, request

from django.conf import settings
from django.core.cache import cache

from .travel_pricing import TravelPricingError, apply_flight_pricing


logger = logging.getLogger(__name__)
DUFFEL_OFFERS_PIPELINE_VERSION = 'paginated-offers-v1'


class FlightSearchError(Exception):
    """Base exception for sanitized supplier failures."""


class FlightSearchNotConfigured(FlightSearchError):
    pass


class FlightSearchTimeout(FlightSearchError):
    pass


class FlightSearchProviderError(FlightSearchError):
    pass


class FlightSearchValidationError(FlightSearchError):
    pass


def _ssl_context():
    context = ssl.create_default_context()
    if (
        settings.FLIGHT_SEARCH_RELAX_TLS_STRICT
        and hasattr(ssl, 'VERIFY_X509_STRICT')
    ):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _passengers(criteria):
    passengers = []
    passengers.extend({'type': 'adult'} for _ in range(criteria['adults']))
    passengers.extend({'age': age} for age in criteria['childAges'])
    passengers.extend({'age': age} for age in criteria['infantAges'])
    return passengers


def build_duffel_request(criteria):
    slices = [
        {
            'origin': criteria['origin'],
            'destination': criteria['destination'],
            'departure_date': criteria['departureDate'].isoformat(),
        }
    ]
    if criteria.get('returnDate'):
        slices.append(
            {
                'origin': criteria['destination'],
                'destination': criteria['origin'],
                'departure_date': criteria['returnDate'].isoformat(),
            }
        )

    return {
        'data': {
            'cabin_class': criteria['travelClass'].lower(),
            'slices': slices,
            'passengers': _passengers(criteria),
            'max_connections': 2,
        }
    }


def _location(value):
    if not isinstance(value, dict):
        return {'iataCode': ''}
    result = {
        'iataCode': value.get('iata_code') or value.get('iataCode') or '',
    }
    terminal = value.get('terminal')
    if terminal:
        result['terminal'] = terminal
    name = value.get('name')
    if name:
        result['name'] = name
    return result


def _carrier(segment):
    carrier = segment.get('marketing_carrier') or {}
    return {
        'code': carrier.get('iata_code') or '',
        'name': carrier.get('name') or '',
        'logo': carrier.get('logo_symbol_url') or carrier.get('logo_lockup_url') or '',
    }


def _operating_carrier(segment):
    carrier = segment.get('operating_carrier') or {}
    return {
        'code': carrier.get('iata_code') or '',
        'name': carrier.get('name') or '',
        'logo': carrier.get('logo_symbol_url') or carrier.get('logo_lockup_url') or '',
    }


def _baggage_allowances(offer):
    allowances_by_traveler_leg = []
    for flight_slice in offer.get('slices', []):
        for segment in flight_slice.get('segments', []):
            for passenger in segment.get('passengers', []):
                allowances = set()
                for baggage in passenger.get('baggages', []):
                    quantity = baggage.get('quantity')
                    baggage_type = baggage.get('type')
                    if quantity is None or baggage_type not in {'checked', 'carry_on'}:
                        continue
                    label = 'checked bag' if baggage_type == 'checked' else 'carry-on bag'
                    plural = '' if quantity == 1 else 's'
                    allowances.add(f'{quantity} {label}{plural}')
                allowances_by_traveler_leg.append(tuple(sorted(allowances)))
    if not allowances_by_traveler_leg:
        return []
    if len(set(allowances_by_traveler_leg)) == 1:
        return list(allowances_by_traveler_leg[0])
    return ['Allowances vary by traveler or flight leg']


def _refund_condition(offer):
    conditions = offer.get('conditions') or {}
    refund_condition = conditions.get('refund_before_departure') or {}
    allowed = refund_condition.get('allowed')
    if not isinstance(allowed, bool):
        return None
    return {
        'allowed': allowed,
        'penaltyAmount': refund_condition.get('penalty_amount'),
        'penaltyCurrency': refund_condition.get('penalty_currency'),
    }


def normalize_duffel_response(payload):
    container = payload.get('data', {}) if isinstance(payload, dict) else {}
    offers = container.get('offers', []) if isinstance(container, dict) else []
    normalized = []

    for offer in offers if isinstance(offers, list) else []:
        if not isinstance(offer, dict):
            continue
        refund_condition = _refund_condition(offer)
        itineraries = []
        for flight_slice in offer.get('slices', []):
            if not isinstance(flight_slice, dict):
                continue
            segments = []
            for segment in flight_slice.get('segments', []):
                if not isinstance(segment, dict):
                    continue
                carrier = _carrier(segment)
                operating_carrier = _operating_carrier(segment)
                aircraft = segment.get('aircraft') or {}
                departure = _location(segment.get('origin'))
                arrival = _location(segment.get('destination'))
                if segment.get('origin_terminal'):
                    departure['terminal'] = segment['origin_terminal']
                if segment.get('destination_terminal'):
                    arrival['terminal'] = segment['destination_terminal']
                segments.append(
                    {
                        'id': segment.get('id'),
                        'departure': {
                            **departure,
                            'at': segment.get('departing_at'),
                        },
                        'arrival': {
                            **arrival,
                            'at': segment.get('arriving_at'),
                        },
                        'duration': segment.get('duration'),
                        'carrierCode': carrier['code'],
                        'carrierName': carrier['name'],
                        'carrierLogo': carrier['logo'],
                        'operatingCarrierCode': operating_carrier['code'],
                        'operatingCarrierName': operating_carrier['name'],
                        'operatingCarrierLogo': operating_carrier['logo'],
                        'flightNumber': segment.get('marketing_carrier_flight_number'),
                        'numberOfStops': len(segment.get('stops') or []),
                        'aircraft': {
                            'code': aircraft.get('iata_code') or '',
                            'name': aircraft.get('name') or '',
                        },
                    }
                )
            itineraries.append(
                {
                    'id': flight_slice.get('id'),
                    'duration': flight_slice.get('duration'),
                    'segments': segments,
                }
            )

        normalized.append(
            {
                'id': offer.get('id'),
                'provider': 'Duffel',
                'expiresAt': offer.get('expires_at'),
                'liveMode': offer.get('live_mode'),
                'price': {
                    'currency': offer.get('total_currency') or '',
                    'grandTotal': offer.get('total_amount') or '',
                    'base': offer.get('base_amount') or '',
                },
                'baggage': _baggage_allowances(offer),
                'refundable': (
                    refund_condition['allowed'] if refund_condition else None
                ),
                'refundCondition': refund_condition,
                'itineraries': itineraries,
            }
        )

    return {
        'data': normalized,
        'meta': {
            'provider': 'Duffel',
            'offerRequestId': container.get('id') if isinstance(container, dict) else None,
        },
    }


def _perform_duffel_request(supplier_request):
    try:
        with request.urlopen(
            supplier_request,
            timeout=settings.FLIGHT_SEARCH_TIMEOUT_SECONDS,
            context=_ssl_context(),
        ) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (TimeoutError, socket.timeout) as exc:
        logger.warning('Flight supplier request timed out')
        raise FlightSearchTimeout(
            'The flight supplier took too long to respond.'
        ) from exc
    except error.HTTPError as exc:
        request_id = (
            exc.headers.get('x-request-id') if exc.headers is not None else None
        )
        logger.warning(
            'Flight supplier returned HTTP %s (request_id=%s)',
            exc.code,
            request_id or 'unknown',
        )
        if exc.code in {400, 422}:
            raise FlightSearchValidationError(
                'One or more flight search details were not accepted.'
            ) from exc
        if exc.code == 429:
            raise FlightSearchProviderError(
                'The flight supplier is busy. Please try again shortly.'
            ) from exc
        raise FlightSearchProviderError(
            'Live flight search is temporarily unavailable.'
        ) from exc
    except error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            logger.warning('Flight supplier request timed out')
            raise FlightSearchTimeout(
                'The flight supplier took too long to respond.'
            ) from exc
        logger.warning('Flight supplier request failed: %s', exc.__class__.__name__)
        raise FlightSearchProviderError(
            'Live flight search is temporarily unavailable.'
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning('Flight supplier request failed: %s', exc.__class__.__name__)
        raise FlightSearchProviderError(
            'Live flight search is temporarily unavailable.'
        ) from exc

    if not isinstance(payload, dict):
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        )
    return payload


def _search_duffel(criteria):
    access_token = settings.DUFFEL_ACCESS_TOKEN.strip()
    if not access_token:
        raise FlightSearchNotConfigured(
            'Live flight search has not been configured.'
        )

    result_limit = settings.FLIGHT_SEARCH_RESULT_LIMIT
    base_url = settings.DUFFEL_API_BASE_URL.rstrip('/')
    common_headers = {
        'Authorization': f'Bearer {access_token}',
        'Duffel-Version': settings.DUFFEL_API_VERSION,
        'Accept': 'application/json',
    }
    offer_request_query = parse.urlencode(
        {
            'return_offers': 'false',
            'supplier_timeout': settings.DUFFEL_SUPPLIER_TIMEOUT_MS,
        }
    )
    offer_request = request.Request(
        f'{base_url}/air/offer_requests?{offer_request_query}',
        data=json.dumps(build_duffel_request(criteria)).encode('utf-8'),
        headers={**common_headers, 'Content-Type': 'application/json'},
        method='POST',
    )
    offer_request_payload = _perform_duffel_request(offer_request)
    offer_request_data = offer_request_payload.get('data')
    offer_request_id = (
        offer_request_data.get('id')
        if isinstance(offer_request_data, dict)
        else None
    )
    if not isinstance(offer_request_id, str) or not offer_request_id.strip():
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        )

    offers_query = parse.urlencode(
        {
            'offer_request_id': offer_request_id,
            'limit': result_limit,
            'sort': 'total_amount',
            'max_connections': 2,
        }
    )
    offers_request = request.Request(
        f'{base_url}/air/offers?{offers_query}',
        headers=common_headers,
        method='GET',
    )
    offers_payload = _perform_duffel_request(offers_request)
    raw_offers = offers_payload.get('data')
    if not isinstance(raw_offers, list):
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        )
    raw_offers = raw_offers[:result_limit]
    payload = {
        'data': {
            'id': offer_request_id,
            'offers': raw_offers,
        }
    }

    try:
        results = normalize_duffel_response(payload)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning('Flight supplier returned malformed offer data')
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        ) from exc
    contains_test_data = any(
        offer.get('liveMode') is False for offer in results['data']
    )
    if contains_test_data and not settings.ALLOW_DUFFEL_TEST_DATA:
        raise FlightSearchProviderError(
            'The flight supplier returned test data, which is disabled in production.'
        )
    list_meta = offers_payload.get('meta')
    if not isinstance(list_meta, dict):
        list_meta = {}
    results['meta']['testData'] = contains_test_data
    results['meta']['resultLimit'] = result_limit
    results['meta']['sort'] = 'total_amount'
    results['meta']['returnedOfferCount'] = len(results['data'])
    results['meta']['hasMoreOffers'] = bool(list_meta.get('after'))
    return results


def _normalized_location_query(query):
    return ' '.join(query.split()).casefold()


def _place_text(value, *, uppercase=False):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    return value.upper() if uppercase else value


def normalize_duffel_places(payload):
    places = payload.get('data', []) if isinstance(payload, dict) else []
    normalized = []

    for place in places if isinstance(places, list) else []:
        if not isinstance(place, dict):
            continue

        place_type = _place_text(place.get('type')).lower()
        place_id = _place_text(place.get('id'))
        iata_code = _place_text(place.get('iata_code'), uppercase=True)
        name = _place_text(place.get('name'))
        if (
            place_type not in {'airport', 'city'}
            or not place_id
            or len(iata_code) != 3
            or not name
        ):
            continue

        city = place.get('city') if isinstance(place.get('city'), dict) else {}
        city_name = _place_text(place.get('city_name')) or _place_text(
            city.get('name')
        )
        if place_type == 'city' and not city_name:
            city_name = name

        airports = place.get('airports')
        airport_count = 0
        if place_type == 'city' and isinstance(airports, list):
            airport_count = sum(isinstance(airport, dict) for airport in airports)

        normalized.append(
            {
                'id': place_id,
                'type': place_type,
                'iataCode': iata_code,
                'name': name,
                'cityName': city_name or None,
                'countryCode': _place_text(
                    place.get('iata_country_code'),
                    uppercase=True,
                ) or None,
                'timeZone': _place_text(place.get('time_zone')) or None,
                'airportCount': airport_count,
            }
        )

    return normalized


def _search_duffel_locations(query):
    access_token = settings.DUFFEL_ACCESS_TOKEN.strip()
    if not access_token:
        raise FlightSearchNotConfigured(
            'Flight location search has not been configured.'
        )

    url = (
        f"{settings.DUFFEL_API_BASE_URL.rstrip('/')}/places/suggestions?"
        f"{parse.urlencode({'query': query})}"
    )
    supplier_request = request.Request(
        url,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Duffel-Version': settings.DUFFEL_API_VERSION,
            'Accept': 'application/json',
        },
        method='GET',
    )

    try:
        with request.urlopen(
            supplier_request,
            timeout=settings.FLIGHT_SEARCH_TIMEOUT_SECONDS,
            context=_ssl_context(),
        ) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (TimeoutError, socket.timeout) as exc:
        logger.warning('Flight location supplier request timed out')
        raise FlightSearchTimeout(
            'The flight supplier took too long to respond.'
        ) from exc
    except error.HTTPError as exc:
        request_id = (
            exc.headers.get('x-request-id') if exc.headers is not None else None
        )
        logger.warning(
            'Flight location supplier returned HTTP %s (request_id=%s)',
            exc.code,
            request_id or 'unknown',
        )
        if exc.code in {400, 422}:
            raise FlightSearchValidationError(
                'The flight location query was not accepted.'
            ) from exc
        if exc.code == 429:
            raise FlightSearchProviderError(
                'The flight supplier is busy. Please try again shortly.'
            ) from exc
        raise FlightSearchProviderError(
            'Flight location search is temporarily unavailable.'
        ) from exc
    except error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            logger.warning('Flight location supplier request timed out')
            raise FlightSearchTimeout(
                'The flight supplier took too long to respond.'
            ) from exc
        logger.warning(
            'Flight location supplier request failed: %s',
            exc.__class__.__name__,
        )
        raise FlightSearchProviderError(
            'Flight location search is temporarily unavailable.'
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            'Flight location supplier request failed: %s',
            exc.__class__.__name__,
        )
        raise FlightSearchProviderError(
            'Flight location search is temporarily unavailable.'
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        )
    try:
        return {'data': normalize_duffel_places(payload)}
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning('Flight supplier returned malformed location data')
        raise FlightSearchProviderError(
            'The flight supplier returned an invalid response.'
        ) from exc


def _location_cache_key(provider, query):
    query_digest = hashlib.sha256(query.encode('utf-8')).hexdigest()
    configuration_digest = hashlib.sha256(
        '|'.join(
            [
                provider,
                settings.DUFFEL_ACCESS_TOKEN,
                settings.DUFFEL_API_BASE_URL,
                settings.DUFFEL_API_VERSION,
            ]
        ).encode('utf-8')
    ).hexdigest()[:16]
    return f'flight-locations:{configuration_digest}:{query_digest}'


def search_flight_locations(query):
    provider = settings.FLIGHT_SEARCH_PROVIDER.strip().lower()
    if not provider:
        raise FlightSearchNotConfigured(
            'Flight location search has not been configured.'
        )

    normalized_query = _normalized_location_query(query)
    cache_key = _location_cache_key(provider, normalized_query)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if provider == 'duffel':
        results = _search_duffel_locations(normalized_query)
    else:
        raise FlightSearchNotConfigured(
            'The configured flight location provider is not supported.'
        )

    cache.set(
        cache_key,
        results,
        timeout=settings.FLIGHT_LOCATION_CACHE_SECONDS,
    )
    return results


def _cache_key(provider, criteria):
    serializable = {
        key: value.isoformat() if hasattr(value, 'isoformat') else value
        for key, value in criteria.items()
    }
    criteria_digest = hashlib.sha256(
        json.dumps(serializable, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    configuration_digest = hashlib.sha256(
        '|'.join(
            [
                provider,
                settings.DUFFEL_ACCESS_TOKEN,
                settings.DUFFEL_API_BASE_URL,
                settings.DUFFEL_API_VERSION,
                str(settings.ALLOW_DUFFEL_TEST_DATA),
                str(settings.FLIGHT_SEARCH_RESULT_LIMIT),
                DUFFEL_OFFERS_PIPELINE_VERSION,
            ]
        ).encode('utf-8')
    ).hexdigest()[:16]
    return f'flight-search:{configuration_digest}:{criteria_digest}'


def search_flights(criteria):
    provider = settings.FLIGHT_SEARCH_PROVIDER.strip().lower()
    if not provider:
        raise FlightSearchNotConfigured(
            'Live flight search has not been configured.'
        )
    cache_key = _cache_key(provider, criteria)
    cached = cache.get(cache_key)
    if cached is not None:
        cached_test_data = cached.get('meta', {}).get('testData') is True
        if not cached_test_data or settings.ALLOW_DUFFEL_TEST_DATA:
            try:
                return apply_flight_pricing(cached)
            except TravelPricingError as exc:
                logger.warning('Cached flight offer pricing failed: %s', exc)
                raise FlightSearchProviderError(
                    'A flight price could not be converted to NGN.'
                ) from exc
        cache.delete(cache_key)

    if provider == 'duffel':
        results = _search_duffel(criteria)
    else:
        raise FlightSearchNotConfigured(
            'The configured flight search provider is not supported.'
        )

    cache_seconds = settings.FLIGHT_SEARCH_CACHE_SECONDS
    if not results.get('data'):
        cache_seconds = min(cache_seconds, 30)
    cache.set(cache_key, results, timeout=cache_seconds)
    try:
        return apply_flight_pricing(results)
    except TravelPricingError as exc:
        logger.warning('Flight offer pricing failed: %s', exc)
        raise FlightSearchProviderError(
            'A flight price could not be converted to NGN.'
        ) from exc
