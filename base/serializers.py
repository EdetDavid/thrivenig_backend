import json
import math
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from .models import (
    Claim,
    Contact,
    NewsletterSubscription,
    SubmitCv,
    UserProfile,
    FlightBooking,
    HotelBooking,
    HotelListing,
    TravelPricingSettings,
    TravelSearchLog,
)
from .services.hotel_search import (
    HotelListingUnavailable,
    HotelSearchNotConfigured,
    resolve_hotel_listing,
    resolve_hotel_search_result,
)
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'


class NewsletterSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscription
        fields = ('email',)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class UserSerializerWithToken(serializers.ModelSerializer):
    # Registration intentionally accepts any non-empty password the traveler
    # chooses.  Django's configured password validators remain available for
    # administrative/password-management flows, but are not imposed here.
    password = serializers.CharField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
        max_length=User._meta.get_field('password').max_length,
        style={'input_type': 'password'},
    )
    token = serializers.SerializerMethodField(read_only=True)
    phone = serializers.CharField(source='profile.phone', allow_blank=True, required=False)
    address = serializers.CharField(source='profile.address', allow_blank=True, required=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "token", "first_name", "last_name", "phone", "address"]

    def get_token(self, obj):
        token, _ = Token.objects.get_or_create(user=obj)
        return token.key

    def validate_password(self, value):
        if not value.strip():
            raise serializers.ValidationError('Password cannot be empty.')
        # Preserve every character the user chose, including surrounding
        # whitespace, so the stored credential matches the submitted value.
        return value

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        user = User.objects.create_user(
            username=validated_data.get('username'),
            email=validated_data.get('email'),
            password=validated_data.get('password'),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        Token.objects.get_or_create(user=user)
        profile = UserProfile.objects.get_or_create(user=user)[0]
        profile.phone = profile_data.get('phone', '')
        profile.address = profile_data.get('address', '')
        profile.save()
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source='profile.phone', allow_blank=True, required=False)
    address = serializers.CharField(source='profile.address', allow_blank=True, required=False)
    can_manage_admins = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "address",
            "is_staff",
            "can_manage_admins",
        ]
        read_only_fields = ["id", "username", "is_staff", "can_manage_admins"]

    def get_can_manage_admins(self, obj):
        return bool(obj.is_active and obj.is_staff and obj.is_superuser)

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()
        return instance


def validate_json_snapshot(value, field_name, max_bytes=65536, max_depth=8):
    def inspect(item, depth=0):
        if depth > max_depth:
            raise serializers.ValidationError(
                f"{field_name} is nested too deeply."
            )
        if isinstance(item, dict):
            if len(item) > 100:
                raise serializers.ValidationError(
                    f"{field_name} contains too many fields."
                )
            for nested in item.values():
                inspect(nested, depth + 1)
        elif isinstance(item, list):
            if len(item) > 100:
                raise serializers.ValidationError(
                    f"{field_name} contains too many items."
                )
            for nested in item:
                inspect(nested, depth + 1)

    try:
        inspect(value)
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    except RecursionError as exc:
        raise serializers.ValidationError(
            f"{field_name} is nested too deeply."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError(
            f"{field_name} must contain valid JSON data."
        ) from exc

    if len(encoded.encode('utf-8')) > max_bytes:
        raise serializers.ValidationError(f"{field_name} is too large.")

    return value


class FlightTravelerSerializer(serializers.Serializer):
    name = serializers.CharField(
        min_length=2,
        max_length=150,
        trim_whitespace=True,
    )
    email = serializers.EmailField(max_length=254)
    phone = serializers.RegexField(
        regex=r'^\+?[0-9().\-\s]{7,30}$',
        max_length=30,
        trim_whitespace=True,
        error_messages={'invalid': 'Enter a valid phone number.'},
    )

    def validate_name(self, value):
        if any(ord(character) < 32 for character in value):
            raise serializers.ValidationError('Enter a valid traveler name.')
        value = ' '.join(value.split())
        if not any(character.isalpha() for character in value):
            raise serializers.ValidationError('Enter a valid traveler name.')
        return value

    def validate_phone(self, value):
        digit_count = sum(character.isdigit() for character in value)
        if digit_count < 7 or digit_count > 15:
            raise serializers.ValidationError('Enter a valid phone number.')
        return ' '.join(value.split())


def validate_snapshot_amount(value):
    text_value = str(value)
    whole, separator, fraction = text_value.partition('.')
    if (
        not whole.isdigit()
        or (separator and (not fraction.isdigit() or len(fraction) > 2))
    ):
        raise serializers.ValidationError('Enter a valid fare amount.')
    try:
        amount = Decimal(text_value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise serializers.ValidationError('Enter a valid fare amount.') from exc
    if not amount.is_finite() or amount <= 0 or amount > Decimal('9999999999999999.99'):
        raise serializers.ValidationError('Enter a valid fare amount.')
    decimal_places = max(-amount.as_tuple().exponent, 0)
    if decimal_places > 2:
        raise serializers.ValidationError(
            'Fare amounts cannot contain more than two decimal places.'
        )
    return format(amount, 'f')


class FlightOfferPriceSnapshotSerializer(serializers.Serializer):
    currency = serializers.RegexField(
        regex=r'^[A-Z]{3}$',
        required=False,
        allow_blank=True,
    )
    total = serializers.CharField(
        max_length=30,
        required=False,
        validators=[validate_snapshot_amount],
    )
    grandTotal = serializers.CharField(
        max_length=30,
        required=False,
        validators=[validate_snapshot_amount],
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            return super().to_internal_value(data)
        normalized = data.copy()
        normalized['currency'] = str(normalized.get('currency') or '').upper()
        return super().to_internal_value(normalized)

    def validate(self, attrs):
        if not attrs.get('total') and not attrs.get('grandTotal'):
            raise serializers.ValidationError(
                'The selected offer must include its displayed total.'
            )
        if not attrs.get('currency'):
            raise serializers.ValidationError(
                {'currency': 'The selected offer currency is required.'}
            )
        return attrs


class FlightOfferSegmentSnapshotSerializer(serializers.Serializer):
    departureAirport = serializers.RegexField(
        regex=r'^[A-Z0-9]{3,10}$',
        max_length=10,
    )
    departureAt = serializers.CharField(max_length=50)
    departureTerminal = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    arrivalAirport = serializers.RegexField(
        regex=r'^[A-Z0-9]{3,10}$',
        max_length=10,
    )
    arrivalAt = serializers.CharField(max_length=50)
    arrivalTerminal = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    carrierCode = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
    )
    carrierName = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    operatingCarrierCode = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
    )
    operatingCarrierName = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    flightNumber = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        for field in ('departureAt', 'arrivalAt'):
            value = attrs[field]
            if (
                any(ord(character) < 32 for character in value)
                or parse_datetime(value) is None
            ):
                raise serializers.ValidationError(
                    {field: 'Enter a valid flight date and time.'}
                )
        return attrs


class FlightOfferItinerarySnapshotSerializer(serializers.Serializer):
    label = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    duration = serializers.CharField(
        max_length=30,
        required=False,
        allow_blank=True,
    )
    segments = FlightOfferSegmentSnapshotSerializer(many=True, max_length=12)


class FlightRefundSnapshotSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    penaltyAmount = serializers.CharField(
        max_length=30,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    penaltyCurrency = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
    )


class FlightOfferSnapshotSerializer(serializers.Serializer):
    id = serializers.RegexField(
        regex=r'^[A-Za-z0-9._:-]{1,200}$',
        max_length=200,
    )
    provider = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    expiresAt = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    liveMode = serializers.BooleanField(required=False, allow_null=True)
    price = FlightOfferPriceSnapshotSerializer(required=False)
    itineraries = FlightOfferItinerarySnapshotSerializer(
        many=True,
        max_length=4,
        required=False,
    )
    baggage = serializers.ListField(
        child=serializers.CharField(max_length=100),
        max_length=20,
        required=False,
    )
    refundable = serializers.BooleanField(required=False, allow_null=True)
    refundCondition = FlightRefundSnapshotSerializer(
        required=False,
        allow_null=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get('id') == 'manual-quote':
            normalized = data.copy()
            price = normalized.get('price')
            if isinstance(price, dict) and not (
                price.get('total') or price.get('grandTotal')
            ):
                normalized.pop('price')
            data = normalized
        return super().to_internal_value(data)

    def validate_provider(self, value):
        return ' '.join(value.split())

    def validate(self, attrs):
        if attrs['id'] != 'manual-quote' and 'price' not in attrs:
            raise serializers.ValidationError(
                {'price': 'The selected offer price is required.'}
            )
        return attrs


class FlightCriteriaSerializer(serializers.Serializer):
    CABIN_CLASSES = (
        'ECONOMY',
        'PREMIUM_ECONOMY',
        'BUSINESS',
        'FIRST',
    )

    origin = serializers.RegexField(regex=r'^[A-Z]{3}$')
    destination = serializers.RegexField(regex=r'^[A-Z]{3}$')
    departureDate = serializers.DateField()
    returnDate = serializers.DateField(required=False, allow_null=True)
    adults = serializers.IntegerField(min_value=1, max_value=9, default=1)
    children = serializers.IntegerField(min_value=0, max_value=8, default=0)
    infants = serializers.IntegerField(min_value=0, max_value=4, default=0)
    childAges = serializers.ListField(
        child=serializers.IntegerField(min_value=2, max_value=17),
        default=list,
        max_length=8,
    )
    infantAges = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=1),
        default=list,
        max_length=4,
    )
    travelClass = serializers.ChoiceField(
        choices=CABIN_CLASSES,
        default='ECONOMY',
    )
    tripType = serializers.ChoiceField(
        choices=('one-way', 'round-trip'),
        required=False,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            return super().to_internal_value(data)
        normalized = data.copy()
        normalized['origin'] = str(
            normalized.get('origin', normalized.get('departureCity', ''))
        ).strip().upper()
        normalized['destination'] = str(
            normalized.get('destination', normalized.get('arrivalCity', ''))
        ).strip().upper()
        normalized['travelClass'] = str(
            normalized.get('travelClass', 'ECONOMY')
        ).strip().replace(' ', '_').replace('-', '_').upper()
        if normalized.get('returnDate') == '':
            normalized.pop('returnDate')
        return super().to_internal_value(normalized)

    def validate(self, attrs):
        if attrs['origin'] == attrs['destination']:
            raise serializers.ValidationError(
                {'destination': 'Origin and destination must be different.'}
            )
        if attrs['departureDate'] < timezone.localdate():
            raise serializers.ValidationError(
                {'departureDate': 'Departure date cannot be in the past.'}
            )

        return_date = attrs.get('returnDate')
        if return_date and return_date < attrs['departureDate']:
            raise serializers.ValidationError(
                {'returnDate': 'Return date cannot be before departure.'}
            )

        traveler_count = attrs['adults'] + attrs['children'] + attrs['infants']
        if traveler_count > 9:
            raise serializers.ValidationError(
                'A maximum of nine travelers can be searched at once.'
            )
        if attrs['infants'] > attrs['adults']:
            raise serializers.ValidationError(
                {'infants': 'Each infant must travel with an adult.'}
            )
        if len(attrs['childAges']) != attrs['children']:
            raise serializers.ValidationError(
                {'childAges': 'Provide the age of each child traveler.'}
            )
        if len(attrs['infantAges']) != attrs['infants']:
            raise serializers.ValidationError(
                {'infantAges': 'Provide the age of each infant traveler.'}
            )

        requested_trip_type = attrs.get('tripType')
        if requested_trip_type == 'round-trip' and not return_date:
            raise serializers.ValidationError(
                {'returnDate': 'A return date is required for a round trip.'}
            )
        attrs['tripType'] = 'round-trip' if return_date else 'one-way'
        return attrs


class FlightSearchSerializer(FlightCriteriaSerializer):
    pass


class FlightLocationQuerySerializer(serializers.Serializer):
    query = serializers.CharField(
        min_length=2,
        max_length=80,
        trim_whitespace=True,
    )

    def validate_query(self, value):
        return ' '.join(value.split())


class HotelDestinationSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=200, required=False, allow_blank=True)
    label = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(min_length=2, max_length=100)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    countryCode = serializers.CharField(
        min_length=2,
        max_length=2,
        required=False,
        allow_blank=True,
    )
    latitude = serializers.FloatField(
        min_value=-90,
        max_value=90,
        required=False,
    )
    longitude = serializers.FloatField(
        min_value=-180,
        max_value=180,
        required=False,
    )

    def validate(self, attrs):
        for field in ('id', 'label', 'city', 'country'):
            if field in attrs:
                attrs[field] = ' '.join(attrs[field].split())
        attrs['countryCode'] = str(attrs.get('countryCode') or '').strip().upper()
        latitude = attrs.get('latitude')
        longitude = attrs.get('longitude')
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError(
                'Latitude and longitude must be provided together.'
            )
        if latitude is not None and (
            not math.isfinite(latitude) or not math.isfinite(longitude)
        ):
            raise serializers.ValidationError(
                'Latitude and longitude must be finite numbers.'
            )
        return attrs


class HotelLocationQuerySerializer(serializers.Serializer):
    query = serializers.CharField(
        min_length=2,
        max_length=80,
        trim_whitespace=True,
    )

    def validate_query(self, value):
        return ' '.join(value.split())


class HotelSearchSerializer(serializers.Serializer):
    destination = HotelDestinationSerializer(required=False)
    city = serializers.CharField(
        min_length=2,
        max_length=100,
        required=False,
    )
    checkInDate = serializers.DateField()
    checkOutDate = serializers.DateField()
    rooms = serializers.IntegerField(min_value=1, max_value=9)
    adults = serializers.IntegerField(min_value=1, max_value=20, required=False)
    childAges = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=17),
        required=False,
        allow_empty=True,
        max_length=12,
    )
    guests = serializers.IntegerField(
        min_value=1,
        max_value=20,
        required=False,
    )
    radiusKm = serializers.IntegerField(
        min_value=1,
        max_value=100,
        required=False,
    )
    freeCancellationOnly = serializers.BooleanField(required=False)
    roomType = serializers.CharField(
        min_length=1,
        max_length=100,
        required=False,
        allow_blank=False,
    )

    def validate_city(self, value):
        return ' '.join(value.split())

    def validate_roomType(self, value):
        return ' '.join(value.split())

    def validate(self, attrs):
        destination = attrs.get('destination')
        city = attrs.get('city')
        if destination:
            attrs['city'] = destination['city']
        elif not city:
            raise serializers.ValidationError(
                {'destination': 'Choose a hotel destination.'}
            )
        if (
            str(settings.HOTEL_SEARCH_PROVIDER or '').strip().lower() == 'duffel'
            and (
                not destination
                or destination.get('latitude') is None
                or destination.get('longitude') is None
            )
        ):
            raise serializers.ValidationError(
                {
                    'destination': (
                        'A destination with latitude and longitude is required '
                        'for live hotel search.'
                    )
                }
            )

        child_ages = list(attrs.get('childAges') or [])
        adults = attrs.get('adults')
        legacy_guests = attrs.get('guests')
        if adults is None:
            if legacy_guests is None:
                raise serializers.ValidationError(
                    {'adults': 'Provide the number of adult guests.'}
                )
            adults = legacy_guests - len(child_ages)
            if adults < 1:
                raise serializers.ValidationError(
                    {'adults': 'At least one adult guest is required.'}
                )
        total_guests = adults + len(child_ages)
        if total_guests > 20:
            raise serializers.ValidationError(
                {'childAges': 'A search can include at most 20 guests.'}
            )
        if legacy_guests is not None and legacy_guests != total_guests:
            raise serializers.ValidationError(
                {
                    'guests': (
                        'Guests must equal adults plus the number of child ages.'
                    )
                }
            )
        attrs['adults'] = adults
        attrs['childAges'] = child_ages
        attrs['guests'] = total_guests
        attrs['radiusKm'] = attrs.get(
            'radiusKm',
            settings.HOTEL_SEARCH_DEFAULT_RADIUS_KM,
        )
        attrs['freeCancellationOnly'] = attrs.get(
            'freeCancellationOnly',
            False,
        )

        today = timezone.localdate()
        check_in = attrs['checkInDate']
        check_out = attrs['checkOutDate']
        nights = (check_out - check_in).days

        if check_in < today:
            raise serializers.ValidationError(
                {'checkInDate': 'Check-in date cannot be in the past.'}
            )
        if check_in > today + timedelta(days=330):
            raise serializers.ValidationError(
                {
                    'checkInDate': (
                        'Check-in date cannot be more than 330 days away.'
                    )
                }
            )
        if nights <= 0:
            raise serializers.ValidationError(
                {'checkOutDate': 'Check-out must be after check-in.'}
            )
        if nights > 99:
            raise serializers.ValidationError(
                {'checkOutDate': 'A hotel stay cannot exceed 99 nights.'}
            )
        if attrs['adults'] < attrs['rooms']:
            raise serializers.ValidationError(
                {'adults': 'Each room must have at least one adult guest.'}
            )
        return attrs


def criteria_to_json(criteria):
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in criteria.items()
        if value is not None
    }


class FlightBookingSerializer(serializers.ModelSerializer):
    traveler = FlightTravelerSerializer(write_only=True, required=False)
    criteria = FlightCriteriaSerializer(write_only=True, required=False)
    offer = FlightOfferSnapshotSerializer(write_only=True, required=False)
    reference = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = FlightBooking
        fields = [
            "id",
            "reference",
            "user",
            "traveler",
            "criteria",
            "offer",
            "user_details",
            "flight_details",
            "search_results",
            "booking_type",
            "status",
            "booking_date",
        ]
        read_only_fields = [
            "id",
            "reference",
            "user",
            "booking_type",
            "status",
            "booking_date",
        ]
        extra_kwargs = {
            "user_details": {"write_only": True, "required": False},
            "flight_details": {"write_only": True, "required": False},
            "search_results": {"write_only": True, "required": False},
        }

    def get_reference(self, obj):
        return f"TTF-{obj.id:06d}"

    def validate(self, attrs):
        if 'user' in getattr(self, 'initial_data', {}):
            raise serializers.ValidationError(
                {'user': 'The booking account is determined by authentication.'}
            )

        request = self.context.get('request')
        is_authenticated = bool(
            request and getattr(request.user, 'is_authenticated', False)
        )
        traveler = attrs.get('traveler')
        criteria = attrs.get('criteria')
        using_public_contract = bool(
            traveler is not None or criteria is not None or 'offer' in attrs
        )

        if using_public_contract:
            if traveler is None:
                raise serializers.ValidationError(
                    {'traveler': 'Traveler contact details are required.'}
                )
            if criteria is None:
                raise serializers.ValidationError(
                    {'criteria': 'Flight search criteria are required.'}
                )
            offer = dict(attrs.get('offer') or {'id': 'manual-quote'})
            # Fare data submitted by a browser is deliberately treated as an
            # unverified display snapshot. Consultants must reprice it before
            # accepting payment or confirming a booking.
            offer['verificationStatus'] = 'requires_reprice'
            attrs['offer'] = validate_json_snapshot(
                offer,
                'Offer',
                max_bytes=65536,
            )
        elif not is_authenticated:
            raise serializers.ValidationError(
                'Guest flight requests must include traveler and criteria.'
            )
        else:
            user_details = attrs.get('user_details')
            flight_details = attrs.get('flight_details')
            if not isinstance(user_details, dict) or not user_details:
                raise serializers.ValidationError(
                    {'user_details': 'User details are required.'}
                )
            if not isinstance(flight_details, dict) or not flight_details:
                raise serializers.ValidationError(
                    {'flight_details': 'Flight details are required.'}
                )
            validate_json_snapshot(
                user_details,
                'User details',
                max_bytes=16384,
            )
            validate_json_snapshot(
                flight_details,
                'Flight details',
                max_bytes=32768,
            )
            if attrs.get('search_results') is not None:
                validate_json_snapshot(
                    attrs['search_results'],
                    'Search results',
                    max_bytes=65536,
                )

        return attrs

    def create(self, validated_data):
        traveler = validated_data.pop('traveler', None)
        criteria = validated_data.pop('criteria', None)
        offer = validated_data.pop('offer', None)

        if traveler is not None:
            traveler_snapshot = dict(traveler)
            validated_data['guest_name'] = traveler_snapshot['name']
            validated_data['guest_email'] = traveler_snapshot['email']
            validated_data['guest_phone'] = traveler_snapshot['phone']
            validated_data['user_details'] = traveler_snapshot
        if criteria is not None:
            validated_data['flight_details'] = criteria_to_json(criteria)
        if offer is not None:
            validated_data['search_results'] = offer

        return super().create(validated_data)


class HotelBookingSerializer(serializers.ModelSerializer):
    reference = serializers.SerializerMethodField(read_only=True)
    listingId = serializers.PrimaryKeyRelatedField(
        source='listing',
        queryset=HotelListing.objects.all(),
        required=False,
        allow_null=True,
    )
    criteria = HotelSearchSerializer(write_only=True, required=False)
    searchResultId = serializers.CharField(
        max_length=200,
        write_only=True,
        required=False,
    )

    class Meta:
        model = HotelBooking
        fields = [
            "id",
            "reference",
            "user",
            "listingId",
            "searchResultId",
            "criteria",
            "user_details",
            "hotel_details",
            "search_results",
            "booking_type",
            "status",
            "booking_date",
        ]
        read_only_fields = [
            "id",
            "reference",
            "user",
            "booking_type",
            "status",
            "booking_date",
        ]
        extra_kwargs = {
            'user_details': {'required': False},
            'hotel_details': {'required': False},
            'search_results': {'required': False},
        }

    def get_reference(self, obj):
        return f'TTH-{obj.id:06d}'

    def validate(self, attrs):
        listing = attrs.get('listing')
        search_result_id = attrs.get('searchResultId')
        criteria = attrs.get('criteria')
        using_structured_contract = (
            listing is not None
            or search_result_id is not None
            or criteria is not None
        )

        if using_structured_contract:
            if listing is not None and search_result_id is not None:
                raise serializers.ValidationError(
                    'Use either listingId or searchResultId, not both.'
                )
            if listing is None and search_result_id is None:
                raise serializers.ValidationError(
                    {
                        'searchResultId': (
                            'A live search result or local hotel listing is required.'
                        )
                    }
                )
            if criteria is None:
                raise serializers.ValidationError(
                    {'criteria': 'Hotel search criteria are required.'}
                )
            try:
                if search_result_id is not None:
                    attrs['_resolved_result'] = resolve_hotel_search_result(
                        search_result_id,
                        criteria,
                    )
                else:
                    attrs['_resolved_result'] = resolve_hotel_listing(
                        listing,
                        criteria,
                    )
            except (HotelListingUnavailable, HotelSearchNotConfigured) as exc:
                field = 'searchResultId' if search_result_id is not None else 'listingId'
                raise serializers.ValidationError({field: str(exc)}) from exc

            # Public price and listing snapshots are always server-resolved.
            attrs.pop('user_details', None)
            attrs.pop('hotel_details', None)
            attrs.pop('search_results', None)
        else:
            hotel_details = attrs.get('hotel_details')
            if not isinstance(hotel_details, dict) or not hotel_details:
                raise serializers.ValidationError(
                    {'hotel_details': 'Hotel details are required.'}
                )
            validate_json_snapshot(
                hotel_details,
                'Hotel details',
                max_bytes=32768,
            )
            if attrs.get('user_details') is not None:
                validate_json_snapshot(
                    attrs['user_details'],
                    'User details',
                    max_bytes=16384,
                )
            if attrs.get('search_results') is not None:
                validate_json_snapshot(
                    attrs['search_results'],
                    'Search results',
                    max_bytes=65536,
                )
        return attrs

    def create(self, validated_data):
        criteria = validated_data.pop('criteria', None)
        validated_data.pop('searchResultId', None)
        resolved_result = validated_data.pop('_resolved_result', None)

        if resolved_result is not None:
            validated_data['hotel_details'] = {
                'listingId': resolved_result['listingId'],
                'searchResultId': resolved_result['searchResultId'],
                'property': resolved_result['property'],
                'room': resolved_result['room'],
                'stay': resolved_result['stay'],
            }
            validated_data['search_results'] = resolved_result
            user = validated_data.get('user')
            profile = getattr(user, 'profile', None) if user else None
            validated_data['user_details'] = {
                'username': user.username if user else '',
                'email': user.email if user else '',
                'first_name': user.first_name if user else '',
                'last_name': user.last_name if user else '',
                'phone': profile.phone if profile else '',
                'address': profile.address if profile else '',
            }

        return super().create(validated_data)


class TravelAdminHotelListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = HotelListing
        fields = [
            'id',
            'name',
            'city',
            'country',
            'address',
            'room_type',
            'nightly_amount',
            'source_currency',
            'max_guests',
            'star_rating',
            'image_url',
            'amenities',
            'available_rooms',
            'active',
            'test_data',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_amenities(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Amenities must be a list.')
        if len(value) > 30:
            raise serializers.ValidationError(
                'A listing can contain at most 30 amenities.'
            )
        normalized = []
        for amenity in value:
            if not isinstance(amenity, str):
                raise serializers.ValidationError(
                    'Each amenity must be text.'
                )
            item = ' '.join(amenity.split())
            if not item or len(item) > 80:
                raise serializers.ValidationError(
                    'Each amenity must contain between 1 and 80 characters.'
                )
            normalized.append(item)
        return normalized

    def validate(self, attrs):
        for field_name in ('name', 'city', 'country', 'address', 'room_type'):
            if field_name in attrs:
                attrs[field_name] = ' '.join(attrs[field_name].split())
        return attrs


class TravelAdminUserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name']


class TravelAdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    phone = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    flight_request_count = serializers.IntegerField(read_only=True)
    hotel_request_count = serializers.IntegerField(read_only=True)
    search_count = serializers.IntegerField(read_only=True)
    can_manage_admins = serializers.SerializerMethodField()
    # This is deliberately separate from ``can_manage_admins``: an inactive
    # superuser cannot manage roles, but their protected role must still be
    # visible to clients rendering role-management controls.
    admin_access_protected = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
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
            'can_manage_admins',
            'admin_access_protected',
            'date_joined',
            'last_login',
            'flight_request_count',
            'hotel_request_count',
            'search_count',
        ]
        read_only_fields = fields

    def get_phone(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.phone if profile else ''

    def get_address(self, obj):
        profile = getattr(obj, 'profile', None)
        return profile.address if profile else ''

    def get_can_manage_admins(self, obj):
        return bool(obj.is_active and obj.is_staff and obj.is_superuser)

    def get_admin_access_protected(self, obj):
        return bool(obj.is_superuser)


class TravelAdminUserRoleSerializer(TravelAdminUserSerializer):
    """Allow a site owner to grant or revoke travel-admin access only."""

    class Meta(TravelAdminUserSerializer.Meta):
        read_only_fields = [
            field
            for field in TravelAdminUserSerializer.Meta.fields
            if field != 'is_staff'
        ]

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unexpected_fields = set(data) - {'is_staff'}
            if unexpected_fields:
                raise serializers.ValidationError(
                    {
                        field: 'This field cannot be changed here.'
                        for field in sorted(unexpected_fields)
                    }
                )
            if 'is_staff' in data and type(data['is_staff']) is not bool:
                raise serializers.ValidationError(
                    {
                        'is_staff': (
                            'This value must be the boolean true or false.'
                        )
                    }
                )
        return super().to_internal_value(data)

    def validate(self, attrs):
        # PATCH normally permits an empty payload, but this endpoint represents
        # one explicit role change and therefore requires the intended value.
        if 'is_staff' not in attrs:
            raise serializers.ValidationError(
                {'is_staff': 'This field is required.'}
            )

        desired_status = attrs['is_staff']
        if self.instance and desired_status and not self.instance.is_active:
            raise serializers.ValidationError(
                {
                    'is_staff': (
                        'An inactive user cannot be promoted. Activate the '
                        'account first.'
                    )
                }
            )
        if self.instance and not desired_status:
            request = self.context.get('request')
            if request and request.user.pk == self.instance.pk:
                raise serializers.ValidationError(
                    {'is_staff': 'You cannot remove your own admin access.'}
                )
            if self.instance.is_superuser:
                raise serializers.ValidationError(
                    {'is_staff': 'Superuser admin access cannot be removed here.'}
                )
        return attrs

    def update(self, instance, validated_data):
        desired_status = validated_data['is_staff']
        if desired_status:
            changed = User.objects.filter(
                pk=instance.pk,
                is_active=True,
                is_staff=False,
            ).update(is_staff=True)
        else:
            request = self.context.get('request')
            if request and request.user.pk == instance.pk:
                raise serializers.ValidationError(
                    {'is_staff': 'You cannot remove your own admin access.'}
                )
            changed = User.objects.filter(
                pk=instance.pk,
                is_staff=True,
                is_superuser=False,
            ).update(is_staff=False)

        current_status = User.objects.only(
            'is_active',
            'is_staff',
            'is_superuser',
        ).get(pk=instance.pk)
        if desired_status and not current_status.is_active:
            raise serializers.ValidationError(
                {
                    'is_staff': (
                        'An inactive user cannot be promoted. Activate the '
                        'account first.'
                    )
                }
            )
        if not desired_status and current_status.is_superuser:
            raise serializers.ValidationError(
                {'is_staff': 'Superuser admin access cannot be removed here.'}
            )

        instance.is_active = current_status.is_active
        instance.is_staff = current_status.is_staff
        instance.is_superuser = current_status.is_superuser
        instance._admin_access_change = (
            ('granted' if desired_status else 'revoked')
            if changed == 1
            else None
        )
        return instance


class TravelPricingSettingsSerializer(serializers.ModelSerializer):
    display_currency = serializers.SerializerMethodField()
    updated_by = TravelAdminUserSummarySerializer(read_only=True)

    class Meta:
        model = TravelPricingSettings
        fields = [
            'id',
            'display_currency',
            'usd_to_ngn_rate',
            'flight_markup_mode',
            'flight_markup_percent',
            'flight_markup_fixed_ngn',
            'hotel_markup_mode',
            'hotel_markup_percent',
            'hotel_markup_fixed_ngn',
            'updated_by',
            'updated_at',
        ]
        read_only_fields = ['id', 'display_currency', 'updated_by', 'updated_at']

    def get_display_currency(self, obj):
        return 'NGN'

    def validate(self, attrs):
        allowed = {
            'usd_to_ngn_rate',
            'flight_markup_mode',
            'flight_markup_percent',
            'flight_markup_fixed_ngn',
            'hotel_markup_mode',
            'hotel_markup_percent',
            'hotel_markup_fixed_ngn',
        }
        unexpected = set(getattr(self, 'initial_data', {})) - allowed
        if unexpected:
            raise serializers.ValidationError(
                {'detail': 'Only travel pricing fields can be updated.'}
            )
        return attrs


class TravelSearchLogSerializer(serializers.ModelSerializer):
    user = TravelAdminUserSummarySerializer(read_only=True)

    class Meta:
        model = TravelSearchLog
        fields = [
            'id',
            'service_type',
            'user',
            'criteria',
            'provider',
            'provider_reference',
            'status',
            'error_code',
            'result_count',
            'display_currency',
            'minimum_price',
            'maximum_price',
            'duration_ms',
            'pricing_snapshot',
            'client_ip_hash',
            'created_at',
        ]
        read_only_fields = fields


class TravelAdminFlightRequestSerializer(serializers.ModelSerializer):
    reference = serializers.SerializerMethodField()
    user = TravelAdminUserSummarySerializer(read_only=True)

    class Meta:
        model = FlightBooking
        fields = [
            'id',
            'reference',
            'user',
            'guest_name',
            'guest_email',
            'guest_phone',
            'user_details',
            'flight_details',
            'search_results',
            'booking_type',
            'status',
            'booking_date',
        ]
        read_only_fields = [
            'id',
            'reference',
            'user',
            'guest_name',
            'guest_email',
            'guest_phone',
            'user_details',
            'flight_details',
            'search_results',
            'booking_type',
            'booking_date',
        ]

    def get_reference(self, obj):
        return f'TTF-{obj.id:06d}'

    def validate(self, attrs):
        unexpected = set(getattr(self, 'initial_data', {})) - {'status'}
        if unexpected:
            raise serializers.ValidationError(
                {'detail': 'Only request status can be updated.'}
            )
        return attrs


class TravelAdminHotelRequestSerializer(serializers.ModelSerializer):
    reference = serializers.SerializerMethodField()
    user = TravelAdminUserSummarySerializer(read_only=True)

    class Meta:
        model = HotelBooking
        fields = [
            'id',
            'reference',
            'user',
            'user_details',
            'hotel_details',
            'search_results',
            'booking_type',
            'status',
            'booking_date',
        ]
        read_only_fields = [
            'id',
            'reference',
            'user',
            'user_details',
            'hotel_details',
            'search_results',
            'booking_type',
            'booking_date',
        ]

    def get_reference(self, obj):
        return f'TTH-{obj.id:06d}'

    def validate(self, attrs):
        unexpected = set(getattr(self, 'initial_data', {})) - {'status'}
        if unexpected:
            raise serializers.ValidationError(
                {'detail': 'Only request status can be updated.'}
            )
        return attrs


class SubmitCvSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmitCv
        fields = '__all__'
