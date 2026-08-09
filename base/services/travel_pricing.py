import copy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from base.models import TravelPricingSettings

from .fx_rates import FxRateError, get_usd_rate


TARGET_CURRENCY = 'NGN'
MONEY_QUANTUM = Decimal('0.01')
PERCENT_BASE = Decimal('100')


class TravelPricingError(ValueError):
    """Raised when a supplier amount cannot safely be priced for customers."""


def _as_decimal(value, field_name):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TravelPricingError(
            f'The supplier returned an invalid {field_name}.'
        ) from exc
    if not amount.is_finite() or amount < 0:
        raise TravelPricingError(
            f'The supplier returned an invalid {field_name}.'
        )
    return amount


def _format_money(value):
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), '.2f')


def _to_ngn(amount, currency, pricing, *, allow_external_fx=False):
    currency = str(currency or '').strip().upper()
    amount = _as_decimal(amount, 'price')
    if currency == TARGET_CURRENCY:
        return amount
    if currency == 'USD':
        rate = _as_decimal(pricing.usd_to_ngn_rate, 'USD to NGN rate')
        if rate <= 0:
            raise TravelPricingError(
                'The configured USD to NGN rate must be greater than zero.'
            )
        return amount * rate
    if allow_external_fx:
        try:
            usd_rate = get_usd_rate(currency)
        except FxRateError as exc:
            raise TravelPricingError(
                f'Currency {currency or "unknown"} could not be converted to NGN.'
            ) from exc
        configured_ngn_rate = _as_decimal(
            pricing.usd_to_ngn_rate,
            'USD to NGN rate',
        )
        if configured_ngn_rate <= 0:
            raise TravelPricingError(
                'The configured USD to NGN rate must be greater than zero.'
            )
        return amount * usd_rate * configured_ngn_rate
    raise TravelPricingError(
        f'Currency {currency or "unknown"} is not configured for NGN conversion.'
    )


def get_travel_pricing_snapshot(pricing=None):
    pricing = pricing or TravelPricingSettings.load()
    return {
        'displayCurrency': TARGET_CURRENCY,
        'usdToNgnRate': str(pricing.usd_to_ngn_rate),
        'flightMarkupMode': pricing.flight_markup_mode,
        'flightMarkupPercent': str(pricing.flight_markup_percent),
        'flightMarkupFixedNgn': str(pricing.flight_markup_fixed_ngn),
        'hotelMarkupMode': pricing.hotel_markup_mode,
        'hotelMarkupPercent': str(pricing.hotel_markup_percent),
        'hotelMarkupFixedNgn': str(pricing.hotel_markup_fixed_ngn),
        'settingsUpdatedAt': (
            pricing.updated_at.isoformat() if pricing.updated_at else None
        ),
    }


def price_amount(amount, currency, markup_percent, pricing=None):
    """Convert a supplier amount to NGN and apply a server-controlled markup."""

    pricing = pricing or TravelPricingSettings.load()
    ngn_amount = _to_ngn(amount, currency, pricing)
    markup = _as_decimal(markup_percent, 'markup')
    customer_amount = ngn_amount * (Decimal('1') + markup / PERCENT_BASE)
    return _format_money(customer_amount)


def _markup_configuration(pricing, service):
    mode = str(getattr(pricing, f'{service}_markup_mode') or '').strip().lower()
    percent = _as_decimal(
        getattr(pricing, f'{service}_markup_percent'),
        f'{service} markup percentage',
    )
    fixed_ngn = _as_decimal(
        getattr(pricing, f'{service}_markup_fixed_ngn'),
        f'{service} fixed markup',
    )
    if mode not in {
        TravelPricingSettings.MARKUP_PERCENTAGE,
        TravelPricingSettings.MARKUP_FIXED,
    }:
        raise TravelPricingError('The configured markup mode is invalid.')
    if percent > Decimal('100'):
        raise TravelPricingError(
            'The configured markup percentage must not exceed 100.'
        )
    return mode, percent, fixed_ngn


def _apply_offer_pricing(results, service):
    pricing = TravelPricingSettings.load()
    priced_results = copy.deepcopy(results)
    offers = priced_results.get('data', [])
    if not isinstance(offers, list):
        raise TravelPricingError('The supplier returned invalid offer data.')

    markup_mode, markup_percent, fixed_markup_ngn = _markup_configuration(
        pricing,
        service,
    )
    for offer in offers:
        if not isinstance(offer, dict):
            raise TravelPricingError('The supplier returned invalid offer data.')
        price = offer.get('price')
        if not isinstance(price, dict):
            raise TravelPricingError('The supplier returned an invalid price.')
        source_currency = str(price.get('currency') or '').strip().upper()
        if price.get('grandTotal') in (None, ''):
            raise TravelPricingError('The supplier returned an invalid total price.')

        source_total_ngn = _to_ngn(
            price['grandTotal'],
            source_currency,
            pricing,
            allow_external_fx=service == 'hotel',
        )
        if markup_mode == TravelPricingSettings.MARKUP_FIXED:
            customer_total_ngn = source_total_ngn + fixed_markup_ngn
            # Apply the same proportional uplift to component prices. This
            # keeps a nightly/base breakdown consistent while adding the fixed
            # amount only once to the itinerary or whole-stay total.
            component_multiplier = (
                customer_total_ngn / source_total_ngn
                if source_total_ngn > 0
                else Decimal('1')
            )
        else:
            component_multiplier = (
                Decimal('1') + markup_percent / PERCENT_BASE
            )
            customer_total_ngn = source_total_ngn * component_multiplier

        price['grandTotal'] = _format_money(customer_total_ngn)
        if price.get('base') not in (None, ''):
            base_ngn = _to_ngn(
                price['base'],
                source_currency,
                pricing,
                allow_external_fx=service == 'hotel',
            )
            price['base'] = _format_money(base_ngn * component_multiplier)
        price['currency'] = TARGET_CURRENCY

        refund_condition = offer.get('refundCondition')
        if isinstance(refund_condition, dict):
            penalty_amount = refund_condition.get('penaltyAmount')
            if penalty_amount not in (None, ''):
                penalty_currency = (
                    refund_condition.get('penaltyCurrency') or source_currency
                )
                # Penalties are converted for display but are not sales revenue,
                # so the travel markup is deliberately not applied to them.
                normalized_penalty_currency = str(
                    penalty_currency or ''
                ).strip().upper()
                if normalized_penalty_currency in {'USD', TARGET_CURRENCY}:
                    refund_condition['penaltyAmount'] = price_amount(
                        penalty_amount,
                        normalized_penalty_currency,
                        Decimal('0'),
                        pricing,
                    )
                    refund_condition['penaltyCurrency'] = TARGET_CURRENCY

    meta = priced_results.setdefault('meta', {})
    if not isinstance(meta, dict):
        raise TravelPricingError('The supplier returned invalid metadata.')
    # Public metadata intentionally omits the rate and markup percentage.
    meta['displayCurrency'] = TARGET_CURRENCY
    return priced_results


def apply_flight_pricing(results):
    return _apply_offer_pricing(results, 'flight')


def apply_hotel_pricing(results):
    """Price hotel results that use the shared {data: [{price: ...}]} contract."""

    return _apply_offer_pricing(results, 'hotel')
