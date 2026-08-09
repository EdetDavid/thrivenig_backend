from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver


class Claim(models.Model):
    insured = models.CharField(max_length=100)
    policy_number = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    file = models.FileField(upload_to='uploads/', blank=True, null=True)

    def __str__(self):
        return self.policy_number


class Contact(models.Model):
    first_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} - {self.phone}"


class NewsletterSubscription(models.Model):
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email


class SubmitCv(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    cv = models.FileField(upload_to='cvs/')
    cover_letter = models.CharField(max_length=2500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.user.username


class FlightBooking(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending confirmation'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='flight_bookings',
        blank=True,
        null=True,
    )
    guest_name = models.CharField(max_length=150, blank=True)
    guest_email = models.EmailField(blank=True, db_index=True)
    guest_phone = models.CharField(max_length=30, blank=True)
    user_details = models.JSONField(blank=True, null=True)
    flight_details = models.JSONField()
    search_results = models.JSONField(blank=True, null=True)
    booking_type = models.CharField(max_length=20, default='flight')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    booking_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        customer = (
            self.user.username
            if self.user_id
            else self.guest_email or self.guest_name or 'guest'
        )
        return f"Flight request #{self.id} for {customer}"


class HotelListing(models.Model):
    CURRENCY_USD = 'USD'
    CURRENCY_NGN = 'NGN'
    CURRENCY_CHOICES = [
        (CURRENCY_USD, 'US dollar'),
        (CURRENCY_NGN, 'Nigerian naira'),
    ]

    name = models.CharField(max_length=160)
    city = models.CharField(max_length=100, db_index=True)
    country = models.CharField(max_length=100, default='Nigeria')
    address = models.CharField(max_length=255, blank=True)
    room_type = models.CharField(max_length=100)
    nightly_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    source_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default=CURRENCY_NGN,
    )
    max_guests = models.PositiveSmallIntegerField(
        default=2,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(20),
        ],
    )
    star_rating = models.PositiveSmallIntegerField(
        default=3,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
    )
    image_url = models.URLField(blank=True)
    amenities = models.JSONField(default=list, blank=True)
    available_rooms = models.PositiveSmallIntegerField(
        default=1,
        validators=[MaxValueValidator(100)],
    )
    active = models.BooleanField(default=True, db_index=True)
    test_data = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('city', 'name', 'room_type', 'id')
        indexes = [
            models.Index(
                fields=('city', 'active'),
                name='hotel_listing_city_active',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(nightly_amount__gt=0),
                name='hotel_lst_price_gt_zero',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_guests__gte=1)
                    & models.Q(max_guests__lte=20)
                ),
                name='hotel_lst_guests_range',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(star_rating__gte=1)
                    & models.Q(star_rating__lte=5)
                ),
                name='hotel_lst_stars_range',
            ),
            models.CheckConstraint(
                condition=models.Q(available_rooms__lte=100),
                name='hotel_lst_rooms_range',
            ),
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.amenities, list):
            raise ValidationError({'amenities': 'Amenities must be a list.'})
        if len(self.amenities) > 30:
            raise ValidationError(
                {'amenities': 'A listing can contain at most 30 amenities.'}
            )
        normalized = []
        for amenity in self.amenities:
            if not isinstance(amenity, str):
                raise ValidationError(
                    {'amenities': 'Each amenity must be text.'}
                )
            value = ' '.join(amenity.split())
            if not value or len(value) > 80:
                raise ValidationError(
                    {
                        'amenities': (
                            'Each amenity must contain between 1 and 80 '
                            'characters.'
                        )
                    }
                )
            normalized.append(value)
        self.amenities = normalized

    def __str__(self):
        return f'{self.name} - {self.room_type} ({self.city})'


class HotelBooking(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending confirmation'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hotel_bookings')
    listing = models.ForeignKey(
        HotelListing,
        on_delete=models.SET_NULL,
        related_name='hotel_requests',
        blank=True,
        null=True,
    )
    user_details = models.JSONField(blank=True, null=True)
    hotel_details = models.JSONField()
    search_results = models.JSONField(blank=True, null=True)
    booking_type = models.CharField(max_length=20, default='hotel')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    booking_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Hotel booking #{self.id} for {self.user.username}"


class TravelPricingSettings(models.Model):
    """The single, auditable source of customer-facing travel prices."""

    MARKUP_PERCENTAGE = 'percentage'
    MARKUP_FIXED = 'fixed'
    MARKUP_MODE_CHOICES = (
        (MARKUP_PERCENTAGE, 'Percentage'),
        (MARKUP_FIXED, 'Fixed NGN amount'),
    )

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=1,
        editable=False,
    )
    usd_to_ngn_rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default='1600.0000',
        validators=[MinValueValidator(Decimal('0.0001'))],
        help_text='How many Nigerian naira equal one US dollar.',
    )
    flight_markup_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default='0.00',
        validators=[
            MinValueValidator(Decimal('0.00')),
            MaxValueValidator(Decimal('100.00')),
        ],
    )
    flight_markup_mode = models.CharField(
        max_length=12,
        choices=MARKUP_MODE_CHOICES,
        default=MARKUP_PERCENTAGE,
    )
    flight_markup_fixed_ngn = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default='0.00',
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Fixed naira amount added once to the whole itinerary total.',
    )
    hotel_markup_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default='0.00',
        validators=[
            MinValueValidator(Decimal('0.00')),
            MaxValueValidator(Decimal('100.00')),
        ],
    )
    hotel_markup_mode = models.CharField(
        max_length=12,
        choices=MARKUP_MODE_CHOICES,
        default=MARKUP_PERCENTAGE,
    )
    hotel_markup_fixed_ngn = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default='0.00',
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Fixed naira amount added once to the whole stay total.',
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='travel_pricing_updates',
        blank=True,
        null=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'travel pricing settings'
        verbose_name_plural = 'travel pricing settings'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(usd_to_ngn_rate__gt=0),
                name='travel_pricing_positive_usd_ngn_rate',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(flight_markup_percent__gte=0)
                    & models.Q(flight_markup_percent__lte=100)
                ),
                name='travel_pricing_valid_flight_markup',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(hotel_markup_percent__gte=0)
                    & models.Q(hotel_markup_percent__lte=100)
                ),
                name='travel_pricing_valid_hotel_markup',
            ),
            models.CheckConstraint(
                condition=models.Q(flight_markup_fixed_ngn__gte=0),
                name='trv_price_flight_fixed_nonneg',
            ),
            models.CheckConstraint(
                condition=models.Q(hotel_markup_fixed_ngn__gte=0),
                name='trv_price_hotel_fixed_nonneg',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    flight_markup_mode__in=(
                        'percentage',
                        'fixed',
                    )
                ),
                name='trv_price_flight_mode_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    hotel_markup_mode__in=(
                        'percentage',
                        'fixed',
                    )
                ),
                name='trv_price_hotel_mode_valid',
            ),
        ]

    def save(self, *args, **kwargs):
        # A fixed primary key enforces the singleton at database level.
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        settings_record, created = cls.objects.get_or_create(pk=1)
        if created:
            # DecimalField defaults may still be represented as strings on the
            # in-memory object returned by get_or_create. Reload immediately so
            # the first pricing request receives the same Decimal values as all
            # later requests.
            settings_record.refresh_from_db()
        return settings_record

    def __str__(self):
        return 'Travel pricing settings'


class TravelSearchLog(models.Model):
    SERVICE_FLIGHT = 'flight'
    SERVICE_HOTEL = 'hotel'
    SERVICE_CHOICES = [
        (SERVICE_FLIGHT, 'Flight'),
        (SERVICE_HOTEL, 'Hotel'),
    ]
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    service_type = models.CharField(
        max_length=10,
        choices=SERVICE_CHOICES,
        db_index=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='travel_searches',
        blank=True,
        null=True,
    )
    criteria = models.JSONField(default=dict)
    provider = models.CharField(max_length=50, blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        db_index=True,
    )
    error_code = models.CharField(max_length=80, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    display_currency = models.CharField(max_length=3, blank=True)
    minimum_price = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        blank=True,
        null=True,
    )
    maximum_price = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        blank=True,
        null=True,
    )
    duration_ms = models.PositiveIntegerField(default=0)
    pricing_snapshot = models.JSONField(default=dict, blank=True)
    client_ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(
                fields=('service_type', '-created_at'),
                name='trv_search_service_created',
            ),
            models.Index(
                fields=('status', '-created_at'),
                name='trv_search_status_created',
            ),
        ]

    def __str__(self):
        return f'{self.get_service_type_display()} search #{self.pk}'


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created and not kwargs.get("raw", False):
        UserProfile.objects.get_or_create(user=instance)
