import json
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import FlightBooking
from .services.flight_search import (
    FlightSearchProviderError,
    build_duffel_request,
    normalize_duffel_response,
    search_flight_locations,
    search_flights,
)
from .views import TRAVEL_AGENCY_EMAILS, format_detail_rows, send_email


class FlightBookingEmailTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("base.views.send_email")
    def test_registration_sends_user_welcome_and_agency_notification(self, send_email):
        client = APIClient()

        response = client.post(
            "/api/users/",
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "password123",
                "first_name": "New",
                "last_name": "User",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(send_email.call_count, 2)

        user_subject, user_html_content, user_recipients = send_email.call_args_list[0].args
        agency_subject, agency_html_content, agency_recipients = send_email.call_args_list[1].args

        self.assertEqual(user_subject, "Welcome to Thrive Travels")
        self.assertEqual(user_recipients, ["newuser@example.com"])
        self.assertIn("How to Use Your Account", user_html_content)

        self.assertIn("New Thrive Travels User Registered", agency_subject)
        self.assertEqual(agency_recipients, TRAVEL_AGENCY_EMAILS)
        self.assertIn("New User Registration", agency_html_content)
        self.assertIn("newuser@example.com", agency_html_content)

    def test_format_detail_rows_flattens_flight_details(self):
        details = {
            "airline": "Air Peace",
            "flight_number": "P47120",
            "departure": {"airport": "LOS", "time": "09:00"},
            "passengers": [{"first_name": "Ada", "last_name": "Okafor"}],
        }

        rows = format_detail_rows(details)

        self.assertIn({"label": "Airline", "value": "Air Peace"}, rows)
        self.assertIn({"label": "Flight Number", "value": "P47120"}, rows)
        self.assertIn({"label": "Departure - Airport", "value": "LOS"}, rows)
        self.assertIn({"label": "Passengers 1 - First Name", "value": "Ada"}, rows)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="travel@example.com",
    )
    def test_email_uses_configured_sender_and_traveler_reply_to(self):
        send_email(
            "New fare request",
            "<p>Fare request details</p>",
            ["agency@example.com"],
            reply_to=["traveler@example.com"],
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "travel@example.com")
        self.assertEqual(message.to, ["agency@example.com"])
        self.assertEqual(message.reply_to, ["traveler@example.com"])
        self.assertEqual(message.body, "Fare request details")
        self.assertEqual(
            message.alternatives[0].content,
            "<p>Fare request details</p>",
        )

    @patch("base.views.send_email")
    def test_flight_booking_email_goes_to_travel_agency(self, send_email):
        user = User.objects.create_user(
            username="ada",
            email="ada@example.com",
            password="password123",
            first_name="Ada",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/flight-bookings/",
            {
                "user_details": {"first_name": "Ada", "last_name": "Okafor"},
                "flight_details": {
                    "airline": "Air Peace",
                    "flight_number": "P47120",
                    "departure": "LOS",
                    "arrival": "ABV",
                },
                "search_results": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        send_email.assert_called_once()
        subject, html_content, recipients = send_email.call_args.args
        self.assertIn("New Thrive Travels Flight Request", subject)
        self.assertEqual(recipients, TRAVEL_AGENCY_EMAILS)
        self.assertIn("Air Peace", html_content)
        self.assertIn("Flight Number", html_content)

    @patch("base.views.send_email")
    def test_hotel_booking_email_goes_to_travel_agency(self, send_email):
        user = User.objects.create_user(
            username="ada-hotel",
            email="ada.hotel@example.com",
            password="password123",
            first_name="Ada",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/hotel-bookings/",
            {
                "user_details": {"first_name": "Ada", "last_name": "Okafor"},
                "hotel_details": {
                    "hotel_name": "Thrive Suites",
                    "check_in": "2026-07-01",
                    "check_out": "2026-07-05",
                },
                "search_results": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        send_email.assert_called_once()
        subject, html_content, recipients = send_email.call_args.args
        self.assertIn("New Thrive Travels Hotel Booking", subject)
        self.assertEqual(recipients, TRAVEL_AGENCY_EMAILS)
        self.assertIn("Thrive Suites", html_content)
        self.assertIn("Hotel Name", html_content)


class FlexibleRegistrationPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("base.views.send_email")
    def test_registration_accepts_flexible_non_empty_passwords(self, send_email):
        passwords = {
            "single-character": "x",
            "numeric-only": "12345678",
            "common-password": "password",
            "surrounding-whitespace": " x ",
            "maximum-length": "z" * 128,
        }

        for index, (case_name, password) in enumerate(passwords.items()):
            with self.subTest(case=case_name):
                username = f"flexible-password-{index}"
                response = self.client.post(
                    "/api/users/",
                    {
                        "username": username,
                        "email": f"{username}@example.com",
                        "password": password,
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 201, response.data)
                self.assertNotIn("password", response.data)
                user = User.objects.get(username=username)
                self.assertTrue(user.check_password(password))
                self.assertNotEqual(user.password, password)
                login_response = self.client.post(
                    "/api/auth/",
                    {"username": username, "password": password},
                    format="json",
                )
                self.assertEqual(login_response.status_code, 200, login_response.data)
                self.assertIn("token", login_response.data)

        self.assertEqual(send_email.call_count, len(passwords) * 2)

    @patch("base.views.send_email")
    def test_registration_rejects_password_longer_than_django_field(self, send_email):
        response = self.client.post(
            "/api/users/",
            {
                "username": "overlong-password",
                "email": "overlong-password@example.com",
                "password": "z" * 129,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="overlong-password").exists())
        send_email.assert_not_called()

    @patch("base.views.send_email")
    def test_registration_rejects_empty_or_whitespace_only_password(self, send_email):
        for index, password in enumerate(("", "   \t")):
            with self.subTest(password=repr(password)):
                username = f"empty-password-{index}"
                response = self.client.post(
                    "/api/users/",
                    {
                        "username": username,
                        "email": f"{username}@example.com",
                        "password": password,
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.data)
                self.assertFalse(User.objects.filter(username=username).exists())
        send_email.assert_not_called()


class GuestFlightBookingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        departure = timezone.localdate() + timedelta(days=30)
        self.payload = {
            "traveler": {
                "name": "Ada Okafor",
                "email": "ada@example.com",
                "phone": "+234 801 234 5678",
            },
            "criteria": {
                "origin": "LOS",
                "destination": "ABV",
                "departureDate": departure.isoformat(),
                "returnDate": (departure + timedelta(days=7)).isoformat(),
                "adults": 1,
                "children": 0,
                "infants": 0,
                "travelClass": "ECONOMY",
            },
            "offer": {
                "id": "off_test_123",
                "provider": "Duffel",
                "price": {"currency": "NGN", "total": "145000.00"},
                "itineraries": [
                    {
                        "label": "Depart",
                        "duration": "PT1H15M",
                        "segments": [
                            {
                                "departureAirport": "LOS",
                                "departureAt": f"{departure.isoformat()}T09:00:00+01:00",
                                "arrivalAirport": "ABV",
                                "arrivalAt": f"{departure.isoformat()}T10:15:00+01:00",
                                "carrierCode": "P4",
                                "carrierName": "Air Peace",
                                "flightNumber": "7120",
                            }
                        ],
                    }
                ],
                "clientInjectedField": "must not be persisted",
            },
        }

    @patch("base.views.send_email")
    def test_guest_request_is_saved_without_a_user(self, send_email):
        response = self.client.post(
            "/api/flight-bookings/",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = FlightBooking.objects.get()
        self.assertIsNone(booking.user)
        self.assertEqual(booking.guest_name, "Ada Okafor")
        self.assertEqual(booking.guest_email, "ada@example.com")
        self.assertEqual(booking.flight_details["origin"], "LOS")
        self.assertEqual(booking.search_results["id"], "off_test_123")
        self.assertEqual(
            booking.search_results["verificationStatus"],
            "requires_reprice",
        )
        self.assertNotIn("clientInjectedField", booking.search_results)
        self.assertEqual(response.data["reference"], f"TTF-{booking.id:06d}")
        self.assertEqual(response.data["status"], "pending")
        self.assertIn("final price", response.data["message"])

        send_email.assert_called_once()
        subject, html_content, recipients = send_email.call_args.args
        self.assertIn("Flight Request", subject)
        self.assertEqual(recipients, TRAVEL_AGENCY_EMAILS)
        self.assertIn("Ada Okafor", html_content)
        self.assertIn("ada@example.com", html_content)
        self.assertIn("+234 801 234 5678", html_content)
        self.assertIn("145000.00", html_content)
        self.assertIn("Air Peace", html_content)
        self.assertIn("LOS", html_content)
        self.assertIn("ABV", html_content)
        self.assertIn("not a confirmed airline", html_content)
        self.assertIn("must be repriced", html_content)
        self.assertEqual(send_email.call_args.kwargs["reply_to"], ["ada@example.com"])

    @patch("base.views.send_email")
    @patch("base.views.render_to_string", return_value="<p>Fare request</p>")
    def test_email_context_uses_the_persisted_request(
        self,
        render_to_string,
        send_email,
    ):
        response = self.client.post(
            "/api/flight-bookings/",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = FlightBooking.objects.get()
        template_name, context = render_to_string.call_args.args
        self.assertEqual(template_name, "emails/flight_request.html")
        self.assertEqual(context["customer_name"], booking.guest_name)
        self.assertEqual(context["customer_email"], booking.guest_email)
        self.assertEqual(context["customer_phone"], booking.guest_phone)
        self.assertEqual(context["booking_reference"], f"TTF-{booking.id:06d}")
        self.assertIn(
            {"label": "Origin", "value": "LOS"},
            context["flight_detail_rows"],
        )
        self.assertIn(
            {"label": "Price - Total", "value": "145000.00"},
            context["offer_detail_rows"],
        )
        send_email.assert_called_once()

    @patch("base.views.send_email")
    def test_authenticated_request_uses_the_authenticated_user(self, send_email):
        user = User.objects.create_user(
            username="account-owner",
            email="owner@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/flight-bookings/",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(FlightBooking.objects.get().user, user)
        send_email.assert_called_once()

    @patch("base.views.send_email")
    def test_client_cannot_spoof_booking_owner(self, send_email):
        victim = User.objects.create_user(username="victim")
        payload = {**self.payload, "user": victim.id}

        response = self.client.post(
            "/api/flight-bookings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("user", response.data)
        self.assertFalse(FlightBooking.objects.exists())
        send_email.assert_not_called()

    @patch("base.views.send_email")
    def test_invalid_guest_details_are_rejected(self, send_email):
        payload = {
            **self.payload,
            "traveler": {**self.payload["traveler"], "email": "not-an-email"},
            "criteria": {
                **self.payload["criteria"],
                "origin": "LOS",
                "destination": "LOS",
                "infants": 2,
            },
        }

        response = self.client.post(
            "/api/flight-bookings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(FlightBooking.objects.exists())
        send_email.assert_not_called()

    @patch("base.views.send_email")
    def test_malformed_contact_and_nested_offer_are_rejected(self, send_email):
        invalid_phone = {
            **self.payload,
            "traveler": {**self.payload["traveler"], "phone": "+++++++"},
        }
        phone_response = self.client.post(
            "/api/flight-bookings/",
            invalid_phone,
            format="json",
        )

        long_email = f"{'a' * 245}@example.com"
        invalid_email = {
            **self.payload,
            "traveler": {**self.payload["traveler"], "email": long_email},
        }
        email_response = self.client.post(
            "/api/flight-bookings/",
            invalid_email,
            format="json",
        )

        nested = {"value": "offer"}
        for _ in range(10):
            nested = {"nested": nested}
        invalid_offer = {**self.payload, "offer": nested}
        offer_response = self.client.post(
            "/api/flight-bookings/",
            invalid_offer,
            format="json",
        )

        self.assertEqual(phone_response.status_code, 400)
        self.assertEqual(email_response.status_code, 400)
        self.assertEqual(offer_response.status_code, 400)
        self.assertFalse(FlightBooking.objects.exists())
        send_email.assert_not_called()

    @patch("base.views.send_email")
    def test_invalid_selected_offer_price_is_rejected(self, send_email):
        payload = {
            **self.payload,
            "offer": {
                **self.payload["offer"],
                "price": {"currency": "NGN", "total": "-1.00"},
            },
        }

        response = self.client.post(
            "/api/flight-bookings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("offer", response.data)
        self.assertFalse(FlightBooking.objects.exists())
        send_email.assert_not_called()

    @patch("base.views.send_email")
    def test_manual_quote_request_does_not_require_a_displayed_price(self, send_email):
        payload = {
            **self.payload,
            "offer": {
                "id": "manual-quote",
                "provider": "",
                "price": {"currency": "", "total": ""},
            },
        }

        response = self.client.post(
            "/api/flight-bookings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            FlightBooking.objects.get().search_results,
            {
                "id": "manual-quote",
                "provider": "",
                "verificationStatus": "requires_reprice",
            },
        )
        send_email.assert_called_once()

    def test_hotel_and_profile_still_require_authentication(self):
        hotel_response = self.client.post(
            "/api/hotel-bookings/",
            {
                "user_details": {"name": "Guest"},
                "hotel_details": {"hotel_name": "Test Hotel"},
            },
            format="json",
        )
        profile_response = self.client.get("/api/profile/")

        self.assertIn(hotel_response.status_code, (401, 403))
        self.assertIn(profile_response.status_code, (401, 403))

    @patch("base.views.send_email", side_effect=RuntimeError("mail unavailable"))
    def test_email_failure_does_not_report_a_saved_request_as_failed(self, send_email):
        with self.assertLogs("base.views", level="ERROR") as logs:
            response = self.client.post(
                "/api/flight-bookings/",
                self.payload,
                format="json",
            )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(FlightBooking.objects.count(), 1)
        self.assertIn("received", response.data["message"])
        self.assertIn("notification failed", logs.output[0])
        send_email.assert_called_once()

    @patch("base.views.send_email")
    def test_guest_requests_are_throttled(self, send_email):
        responses = [
            self.client.post(
                "/api/flight-bookings/",
                self.payload,
                format="json",
            )
            for _ in range(6)
        ]

        self.assertTrue(all(response.status_code == 201 for response in responses[:5]))
        self.assertEqual(responses[5].status_code, 429)
        self.assertEqual(FlightBooking.objects.count(), 5)
        self.assertEqual(send_email.call_count, 5)


class FlightSearchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        departure = timezone.localdate() + timedelta(days=45)
        self.payload = {
            "origin": "los",
            "destination": "abv",
            "departureDate": departure.isoformat(),
            "returnDate": (departure + timedelta(days=5)).isoformat(),
            "adults": 1,
            "children": 0,
            "infants": 0,
            "travelClass": "economy",
        }

    @override_settings(FLIGHT_SEARCH_PROVIDER="", DUFFEL_ACCESS_TOKEN="")
    def test_missing_provider_configuration_is_explicit(self):
        response = self.client.post(
            "/api/flight-search/",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "FLIGHT_SEARCH_NOT_CONFIGURED")

    @patch("base.views.search_flights")
    def test_public_search_validates_and_returns_normalized_results(self, search):
        search.return_value = {
            "data": [
                {
                    "id": "off_123",
                    "price": {"currency": "NGN", "grandTotal": "100000"},
                    "itineraries": [],
                }
            ],
            "meta": {"provider": "Duffel"},
        }

        response = self.client.post(
            "/api/flight-search/",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"][0]["id"], "off_123")
        criteria = search.call_args.args[0]
        self.assertEqual(criteria["origin"], "LOS")
        self.assertEqual(criteria["travelClass"], "ECONOMY")

    @patch("base.views.search_flights")
    def test_invalid_search_never_calls_the_supplier(self, search):
        payload = {**self.payload, "destination": "los", "infants": 2}

        response = self.client.post(
            "/api/flight-search/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        search.assert_not_called()

    def test_duffel_request_and_response_are_adapted(self):
        criteria = {
            "origin": "LOS",
            "destination": "ABV",
            "departureDate": timezone.localdate() + timedelta(days=30),
            "returnDate": timezone.localdate() + timedelta(days=37),
            "adults": 1,
            "children": 1,
            "infants": 0,
            "childAges": [8],
            "infantAges": [],
            "travelClass": "ECONOMY",
        }
        supplier_body = build_duffel_request(criteria)
        self.assertEqual(supplier_body["data"]["cabin_class"], "economy")
        self.assertEqual(len(supplier_body["data"]["slices"]), 2)
        self.assertEqual(
            supplier_body["data"]["passengers"],
            [{"type": "adult"}, {"age": 8}],
        )
        self.assertEqual(supplier_body["data"]["max_connections"], 2)

        supplier_response = {
            "data": {
                "id": "orq_123",
                "offers": [
                    {
                        "id": "off_123",
                        "live_mode": False,
                        "total_amount": "85000.00",
                        "total_currency": "NGN",
                        "conditions": {
                            "refund_before_departure": {"allowed": True}
                        },
                        "slices": [
                            {
                                "duration": "PT1H10M",
                                "segments": [
                                    {
                                        "id": "seg_123",
                                        "origin": {"iata_code": "LOS"},
                                        "destination": {"iata_code": "ABV"},
                                        "origin_terminal": "D",
                                        "destination_terminal": "1",
                                        "departing_at": "2099-01-01T08:00:00",
                                        "arriving_at": "2099-01-01T09:10:00",
                                        "duration": "PT1H10M",
                                        "marketing_carrier": {
                                            "iata_code": "ZZ",
                                            "name": "Test Air",
                                        },
                                        "operating_carrier": {
                                            "iata_code": "OP",
                                            "name": "Operating Air",
                                        },
                                        "marketing_carrier_flight_number": "101",
                                        "aircraft": {"iata_code": "320"},
                                        "passengers": [
                                            {
                                                "baggages": [
                                                    {"type": "checked", "quantity": 1}
                                                ]
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }

        normalized = normalize_duffel_response(supplier_response)
        offer = normalized["data"][0]
        segment = offer["itineraries"][0]["segments"][0]
        self.assertEqual(normalized["meta"]["offerRequestId"], "orq_123")
        self.assertEqual(offer["price"]["currency"], "NGN")
        self.assertFalse(offer["liveMode"])
        self.assertTrue(offer["refundable"])
        self.assertEqual(offer["baggage"], ["1 checked bag"])
        self.assertEqual(segment["departure"]["iataCode"], "LOS")
        self.assertEqual(segment["departure"]["terminal"], "D")
        self.assertEqual(segment["arrival"]["terminal"], "1")
        self.assertEqual(segment["carrierName"], "Test Air")
        self.assertEqual(segment["operatingCarrierName"], "Operating Air")

    @override_settings(
        FLIGHT_SEARCH_PROVIDER="duffel",
        DUFFEL_ACCESS_TOKEN="server-only-test-token",
        DUFFEL_API_BASE_URL="https://api.duffel.com",
        DUFFEL_API_VERSION="v2",
        DUFFEL_SUPPLIER_TIMEOUT_MS=15000,
        FLIGHT_SEARCH_TIMEOUT_SECONDS=25,
    )
    @patch("base.services.flight_search.request.urlopen")
    def test_duffel_credentials_stay_in_the_server_request(self, urlopen):
        supplier_response = MagicMock()
        supplier_response.read.side_effect = [
            json.dumps({"data": {"id": "orq_empty"}}).encode("utf-8"),
            json.dumps({"data": [], "meta": {}}).encode("utf-8"),
        ]
        urlopen.return_value.__enter__.return_value = supplier_response
        departure = timezone.localdate() + timedelta(days=60)
        criteria = {
            "origin": "LOS",
            "destination": "ABV",
            "departureDate": departure,
            "returnDate": None,
            "adults": 1,
            "children": 0,
            "infants": 0,
            "childAges": [],
            "infantAges": [],
            "travelClass": "ECONOMY",
        }

        result = search_flights(criteria)

        self.assertEqual(urlopen.call_count, 2)
        supplier_request = urlopen.call_args_list[0].args[0]
        offers_request = urlopen.call_args_list[1].args[0]
        self.assertIn("/air/offer_requests?", supplier_request.full_url)
        self.assertIn("return_offers=false", supplier_request.full_url)
        self.assertIn("/air/offers?", offers_request.full_url)
        offers_query = parse_qs(urlparse(offers_request.full_url).query)
        self.assertEqual(offers_query["offer_request_id"], ["orq_empty"])
        self.assertEqual(offers_query["limit"], ["50"])
        self.assertEqual(offers_query["sort"], ["total_amount"])
        self.assertEqual(
            supplier_request.get_header("Authorization"),
            "Bearer server-only-test-token",
        )
        self.assertEqual(supplier_request.get_header("Duffel-version"), "v2")
        request_body = json.loads(supplier_request.data.decode("utf-8"))
        self.assertEqual(request_body["data"]["slices"][0]["origin"], "LOS")
        self.assertNotIn("server-only-test-token", json.dumps(result))

    @override_settings(
        FLIGHT_SEARCH_PROVIDER="duffel",
        DUFFEL_ACCESS_TOKEN="synthetic-test-token",
        DUFFEL_API_BASE_URL="https://api.duffel.com",
        DUFFEL_API_VERSION="v2",
        DUFFEL_SUPPLIER_TIMEOUT_MS=15000,
        FLIGHT_SEARCH_TIMEOUT_SECONDS=25,
        FLIGHT_SEARCH_RESULT_LIMIT=50,
        ALLOW_DUFFEL_TEST_DATA=True,
    )
    @patch("base.services.flight_search.request.urlopen")
    def test_search_returns_only_fifty_lowest_offers(self, urlopen):
        supplier_response = MagicMock()
        supplier_offers = [
            {
                "id": f"off_{index:02d}",
                "live_mode": False,
                "total_amount": f"{100 + index}.00",
                "total_currency": "NGN",
                "conditions": {"refund_before_departure": None},
                "slices": [],
            }
            for index in range(55)
        ]
        supplier_response.read.side_effect = [
            json.dumps({"data": {"id": "orq_many"}}).encode("utf-8"),
            json.dumps(
                {
                    "data": supplier_offers,
                    "meta": {"after": "next-page-cursor"},
                }
            ).encode("utf-8"),
        ]
        urlopen.return_value.__enter__.return_value = supplier_response
        departure = timezone.localdate() + timedelta(days=60)
        criteria = {
            "origin": "LOS",
            "destination": "ABV",
            "departureDate": departure,
            "returnDate": None,
            "adults": 1,
            "children": 0,
            "infants": 0,
            "childAges": [],
            "infantAges": [],
            "travelClass": "ECONOMY",
        }

        result = search_flights(criteria)

        self.assertEqual(len(result["data"]), 50)
        self.assertEqual(result["data"][0]["id"], "off_00")
        self.assertEqual(result["data"][-1]["id"], "off_49")
        self.assertEqual(result["meta"]["resultLimit"], 50)
        self.assertEqual(result["meta"]["returnedOfferCount"], 50)
        self.assertTrue(result["meta"]["hasMoreOffers"])

    @override_settings(
        FLIGHT_SEARCH_PROVIDER="duffel",
        DUFFEL_ACCESS_TOKEN="synthetic-test-token",
        DUFFEL_API_BASE_URL="https://api.duffel.com",
        DUFFEL_API_VERSION="v2",
        DUFFEL_SUPPLIER_TIMEOUT_MS=15000,
        FLIGHT_SEARCH_TIMEOUT_SECONDS=25,
        FLIGHT_SEARCH_CACHE_SECONDS=120,
        ALLOW_DUFFEL_TEST_DATA=False,
    )
    @patch("base.services.flight_search.request.urlopen")
    def test_synthetic_fares_are_blocked_in_production(self, urlopen):
        supplier_response = MagicMock()
        supplier_response.read.side_effect = [
            json.dumps({"data": {"id": "orq_test"}}).encode("utf-8"),
            json.dumps(
                {
                    "data": [
                        {
                            "id": "off_test",
                            "live_mode": False,
                            "total_amount": "50.00",
                            "total_currency": "GBP",
                            "conditions": {"refund_before_departure": None},
                            "slices": [],
                        }
                    ]
                }
            ).encode("utf-8"),
        ]
        urlopen.return_value.__enter__.return_value = supplier_response
        departure = timezone.localdate() + timedelta(days=75)
        criteria = {
            "origin": "LOS",
            "destination": "LHR",
            "departureDate": departure,
            "returnDate": None,
            "adults": 1,
            "children": 0,
            "infants": 0,
            "childAges": [],
            "infantAges": [],
            "travelClass": "ECONOMY",
        }

        with self.assertRaises(FlightSearchProviderError):
            search_flights(criteria)


class FlightLocationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @patch("base.views.search_flight_locations")
    def test_public_location_search_returns_provider_neutral_results(self, search):
        search.return_value = {
            "data": [
                {
                    "id": "arp_lhr_gb",
                    "type": "airport",
                    "iataCode": "LHR",
                    "name": "Heathrow",
                    "cityName": "London",
                    "countryCode": "GB",
                    "timeZone": "Europe/London",
                    "airportCount": 0,
                }
            ]
        }

        response = self.client.get(
            "/api/flight-locations/",
            {"query": "  London  "},
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, search.return_value)
        search.assert_called_once_with("London")

    @patch("base.views.search_flight_locations")
    def test_invalid_location_queries_never_call_the_provider(self, search):
        responses = [
            self.client.get("/api/flight-locations/"),
            self.client.get("/api/flight-locations/", {"query": "x"}),
            self.client.get("/api/flight-locations/", {"query": "x" * 81}),
        ]

        self.assertTrue(all(response.status_code == 400 for response in responses))
        search.assert_not_called()

    @override_settings(
        FLIGHT_SEARCH_PROVIDER="duffel",
        DUFFEL_ACCESS_TOKEN="server-only-location-token",
        DUFFEL_API_BASE_URL="https://api.duffel.com",
        DUFFEL_API_VERSION="v2",
        FLIGHT_SEARCH_TIMEOUT_SECONDS=25,
        FLIGHT_LOCATION_CACHE_SECONDS=3600,
    )
    @patch("base.services.flight_search.request.urlopen")
    def test_duffel_location_headers_normalization_and_cache(self, urlopen):
        supplier_response = MagicMock()
        supplier_response.read.return_value = json.dumps(
            {
                "data": [
                    {
                        "id": "cit_lon_gb",
                        "type": "city",
                        "iata_code": "lon",
                        "name": "London",
                        "iata_country_code": "gb",
                        "time_zone": "Europe/London",
                        "airports": [
                            {"id": "arp_lhr_gb"},
                            {"id": "arp_lgw_gb"},
                        ],
                    },
                    {
                        "id": "arp_lhr_gb",
                        "type": "airport",
                        "iata_code": "lhr",
                        "name": "Heathrow",
                        "city_name": "London",
                        "iata_country_code": "gb",
                        "time_zone": "Europe/London",
                    },
                ]
            }
        ).encode("utf-8")
        urlopen.return_value.__enter__.return_value = supplier_response

        first_result = search_flight_locations("  LoNDon  ")
        cached_result = search_flight_locations("london")

        self.assertEqual(first_result, cached_result)
        self.assertEqual(urlopen.call_count, 1)
        supplier_request = urlopen.call_args.args[0]
        parsed_url = urlparse(supplier_request.full_url)
        self.assertEqual(parsed_url.path, "/places/suggestions")
        self.assertEqual(parse_qs(parsed_url.query), {"query": ["london"]})
        self.assertEqual(supplier_request.get_method(), "GET")
        self.assertIsNone(supplier_request.data)
        self.assertEqual(
            supplier_request.get_header("Authorization"),
            "Bearer server-only-location-token",
        )
        self.assertEqual(supplier_request.get_header("Duffel-version"), "v2")
        self.assertIn("context", urlopen.call_args.kwargs)
        self.assertEqual(
            first_result,
            {
                "data": [
                    {
                        "id": "cit_lon_gb",
                        "type": "city",
                        "iataCode": "LON",
                        "name": "London",
                        "cityName": "London",
                        "countryCode": "GB",
                        "timeZone": "Europe/London",
                        "airportCount": 2,
                    },
                    {
                        "id": "arp_lhr_gb",
                        "type": "airport",
                        "iataCode": "LHR",
                        "name": "Heathrow",
                        "cityName": "London",
                        "countryCode": "GB",
                        "timeZone": "Europe/London",
                        "airportCount": 0,
                    },
                ]
            },
        )
        self.assertNotIn("server-only-location-token", json.dumps(first_result))

        with self.settings(DUFFEL_API_VERSION="v-next"):
            search_flight_locations("LONDON")
        self.assertEqual(urlopen.call_count, 2)

    @override_settings(FLIGHT_SEARCH_PROVIDER="", DUFFEL_ACCESS_TOKEN="")
    def test_missing_location_provider_configuration_is_explicit(self):
        response = self.client.get(
            "/api/flight-locations/",
            {"query": "London"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "FLIGHT_SEARCH_NOT_CONFIGURED")

    @patch("base.views.search_flight_locations", return_value={"data": []})
    def test_public_location_search_is_throttled(self, search):
        responses = [
            self.client.get(
                "/api/flight-locations/",
                {"query": f"London {index}"},
            )
            for index in range(31)
        ]

        self.assertTrue(all(response.status_code == 200 for response in responses[:30]))
        self.assertEqual(responses[30].status_code, 429)
        self.assertEqual(search.call_count, 30)
