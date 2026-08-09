from django.contrib import admin
from .models import (
    Claim,
    Contact,
    FlightBooking,
    HotelBooking,
    HotelListing,
    NewsletterSubscription,
    SubmitCv,
    TravelPricingSettings,
    TravelSearchLog,
)

# Register your models here.


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ('insured', 'policy_number', 'email', 'phone', 'file')
    search_fields = ('insured', 'policy_number', 'email', 'phone', 'file')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'email', 'phone', 'created_at')
    search_fields = ('first_name', 'email', 'phone')


@admin.register(NewsletterSubscription)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ('email',)
    search_fields = ('email',)


@admin.register(SubmitCv)
class SubmitCvAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'created_at')
    search_fields = ('name', 'email',)


@admin.register(FlightBooking)
class FlightBookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'booking_date')
    list_filter = ('status', 'booking_date')
    search_fields = (
        'user__username',
        'user__email',
        'guest_name',
        'guest_email',
        'guest_phone',
    )
    readonly_fields = ('booking_date',)

    @admin.display(description='Customer')
    def customer(self, obj):
        if obj.user_id:
            return obj.user.get_full_name() or obj.user.username
        return obj.guest_name or obj.guest_email or 'Guest'


@admin.register(HotelBooking)
class HotelBookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'listing', 'status', 'booking_date')
    list_filter = ('status', 'booking_date')
    search_fields = (
        'user__username',
        'user__email',
        'listing__name',
        'listing__city',
    )
    readonly_fields = ('booking_date',)


@admin.register(HotelListing)
class HotelListingAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'city',
        'room_type',
        'nightly_amount',
        'source_currency',
        'available_rooms',
        'active',
        'test_data',
        'updated_at',
    )
    list_filter = (
        'active',
        'test_data',
        'source_currency',
        'star_rating',
        'city',
    )
    search_fields = ('name', 'city', 'country', 'address', 'room_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TravelPricingSettings)
class TravelPricingSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'usd_to_ngn_rate',
        'flight_markup_mode',
        'flight_markup_percent',
        'flight_markup_fixed_ngn',
        'hotel_markup_mode',
        'hotel_markup_percent',
        'hotel_markup_fixed_ngn',
        'updated_by',
        'updated_at',
    )
    readonly_fields = ('updated_by', 'updated_at')

    def has_add_permission(self, request):
        return not TravelPricingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(TravelSearchLog)
class TravelSearchLogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'service_type',
        'status',
        'provider',
        'result_count',
        'display_currency',
        'created_at',
    )
    list_filter = ('service_type', 'status', 'provider', 'created_at')
    search_fields = (
        'provider_reference',
        'error_code',
        'user__username',
        'user__email',
    )
    readonly_fields = (
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
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False
