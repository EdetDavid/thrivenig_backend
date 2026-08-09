import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils.crypto import salted_hmac

from base.models import TravelSearchLog

from .travel_pricing import get_travel_pricing_snapshot


logger = logging.getLogger(__name__)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _price_range(results):
    amounts = []
    offers = results.get('data', []) if isinstance(results, dict) else []
    for offer in offers if isinstance(offers, list) else []:
        price = offer.get('price', {}) if isinstance(offer, dict) else {}
        try:
            amount = Decimal(str(price.get('grandTotal')))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount.is_finite() and amount >= 0:
            amounts.append(amount)
    if not amounts:
        return None, None
    return min(amounts), max(amounts)


def _client_ip_hash(request):
    if request is None:
        return ''
    address = str(request.META.get('REMOTE_ADDR') or '').strip()
    if not address:
        return ''
    return salted_hmac('travel-search-client-ip', address).hexdigest()


def record_travel_search(
    *,
    request,
    service_type,
    criteria,
    status,
    duration_ms,
    results=None,
    provider='',
    provider_reference='',
    error_code='',
):
    """Persist privacy-conscious search analytics without blocking a search."""

    results = results if isinstance(results, dict) else {}
    result_data = results.get('data', [])
    result_count = len(result_data) if isinstance(result_data, list) else 0
    minimum_price, maximum_price = _price_range(results)
    meta = results.get('meta', {}) if isinstance(results.get('meta'), dict) else {}
    authenticated_user = getattr(request, 'user', None)
    if not getattr(authenticated_user, 'is_authenticated', False):
        authenticated_user = None

    try:
        return TravelSearchLog.objects.create(
            service_type=service_type,
            user=authenticated_user,
            criteria=_json_value(criteria),
            provider=str(provider or meta.get('provider') or '')[:50],
            provider_reference=str(
                provider_reference or meta.get('offerRequestId') or ''
            )[:100],
            status=status,
            error_code=str(error_code or '')[:80],
            result_count=result_count,
            display_currency=str(meta.get('displayCurrency') or '')[:3],
            minimum_price=minimum_price,
            maximum_price=maximum_price,
            duration_ms=max(0, int(duration_ms)),
            pricing_snapshot=get_travel_pricing_snapshot(),
            client_ip_hash=_client_ip_hash(request),
        )
    except Exception:
        # Analytics must never make live travel search unavailable.
        logger.exception('Could not persist %s search analytics', service_type)
        return None
