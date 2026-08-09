from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from base.models import HotelListing


TEST_LISTINGS = (
    {
        'name': '[TEST DATA] Lagoon View Hotel',
        'city': 'Lagos',
        'country': 'Nigeria',
        'address': 'Test address, Victoria Island',
        'room_type': 'Standard King',
        'nightly_amount': Decimal('85000.00'),
        'source_currency': HotelListing.CURRENCY_NGN,
        'max_guests': 2,
        'star_rating': 4,
        'amenities': ['Wi-Fi', 'Breakfast', 'Airport transfer'],
        'available_rooms': 5,
    },
    {
        'name': '[TEST DATA] Capital City Suites',
        'city': 'Abuja',
        'country': 'Nigeria',
        'address': 'Test address, Central Business District',
        'room_type': 'Deluxe Suite',
        'nightly_amount': Decimal('120.00'),
        'source_currency': HotelListing.CURRENCY_USD,
        'max_guests': 3,
        'star_rating': 4,
        'amenities': ['Wi-Fi', 'Gym', 'Pool'],
        'available_rooms': 4,
    },
    {
        'name': '[TEST DATA] Garden City Lodge',
        'city': 'Port Harcourt',
        'country': 'Nigeria',
        'address': 'Test address, GRA',
        'room_type': 'Family Room',
        'nightly_amount': Decimal('70000.00'),
        'source_currency': HotelListing.CURRENCY_NGN,
        'max_guests': 4,
        'star_rating': 3,
        'amenities': ['Wi-Fi', 'Parking'],
        'available_rooms': 3,
    },
)


class Command(BaseCommand):
    help = 'Seed clearly labelled hotel listings for local QA only.'

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.ALLOW_HOTEL_TEST_DATA:
            raise CommandError(
                'Test hotel seeding requires DEBUG=True and '
                'ALLOW_HOTEL_TEST_DATA=True.'
            )

        created_count = 0
        for listing in TEST_LISTINGS:
            lookup = {
                'name': listing['name'],
                'city': listing['city'],
                'room_type': listing['room_type'],
                'test_data': True,
            }
            defaults = {
                **listing,
                'active': True,
                'test_data': True,
                'image_url': '',
            }
            _, created = HotelListing.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
            created_count += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded {len(TEST_LISTINGS)} test hotel listings '
                f'({created_count} created).'
            )
        )
