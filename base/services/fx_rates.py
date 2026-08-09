import hashlib
import json
import logging
import socket
import ssl
from decimal import Decimal, InvalidOperation
from urllib import error, parse, request
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)


class FxRateError(RuntimeError):
    """Raised when an external currency cannot safely be converted."""


def _cache_key(currency):
    configuration = hashlib.sha256(
        str(settings.HOTEL_FX_API_BASE_URL).encode('utf-8')
    ).hexdigest()[:12]
    return f'hotel-fx-to-usd:v1:{configuration}:{currency}'


def _as_positive_rate(value):
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FxRateError('The exchange-rate service returned invalid data.') from exc
    if not rate.is_finite() or rate <= 0:
        raise FxRateError('The exchange-rate service returned invalid data.')
    return rate


def get_usd_rate(currency):
    """Return the latest number of USD for one unit of ``currency``.

    Frankfurter publishes reference rates rather than transactional rates. A
    deliberately long cache keeps hotel search responsive and avoids treating
    the free public endpoint like a per-offer pricing service.
    """

    currency = str(currency or '').strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise FxRateError('The supplier returned an unsupported currency.')
    if currency == 'USD':
        return Decimal('1')

    cache_key = _cache_key(currency)
    cached = cache.get(cache_key)
    if cached is not None:
        return _as_positive_rate(cached)

    base_url = str(settings.HOTEL_FX_API_BASE_URL).rstrip('/')
    safe_currency = parse.quote(currency, safe='')
    supplier_request = request.Request(
        f'{base_url}/rate/{safe_currency}/USD',
        headers={'Accept': 'application/json'},
        method='GET',
    )
    context = ssl.create_default_context()
    try:
        with urlopen(
            supplier_request,
            timeout=settings.HOTEL_FX_TIMEOUT_SECONDS,
            context=context,
        ) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (TimeoutError, socket.timeout) as exc:
        logger.warning('Hotel FX request timed out for %s', currency)
        raise FxRateError('Currency conversion is temporarily unavailable.') from exc
    except error.HTTPError as exc:
        logger.warning('Hotel FX request returned HTTP %s for %s', exc.code, currency)
        raise FxRateError('Currency conversion is temporarily unavailable.') from exc
    except error.URLError as exc:
        logger.warning('Hotel FX request failed for %s', currency)
        raise FxRateError('Currency conversion is temporarily unavailable.') from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning('Hotel FX response was malformed for %s', currency)
        raise FxRateError('Currency conversion is temporarily unavailable.') from exc

    if not isinstance(payload, dict):
        raise FxRateError('The exchange-rate service returned invalid data.')
    if (
        str(payload.get('base') or '').upper() != currency
        or str(payload.get('quote') or '').upper() != 'USD'
    ):
        raise FxRateError('The exchange-rate service returned invalid data.')
    rate = _as_positive_rate(payload.get('rate'))
    cache.set(
        cache_key,
        str(rate),
        timeout=settings.HOTEL_FX_CACHE_SECONDS,
    )
    return rate
