from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .views import TRAVEL_AGENCY_EMAILS, format_detail_rows


class FlightBookingEmailTests(TestCase):
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
        self.assertIn("New Thrive Travels Flight Booking", subject)
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
