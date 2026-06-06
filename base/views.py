from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.models import User
from django.conf import settings
from rest_framework.generics import CreateAPIView
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Contact, Claim, NewsletterSubscription, SubmitCv, FlightBooking, HotelBooking, UserProfile
from .serializers import (
    ClaimSerializer,
    ContactSerializer,
    NewsletterSubscriptionSerializer,
    SubmitCvSerializer,
    UserSerializerWithToken,
    UserProfileSerializer,
    FlightBookingSerializer,
    HotelBookingSerializer,
)


TRAVEL_AGENCY_EMAILS = ["david.edet@thrivenig.com", "oluwaremilekun.adebowale@thrivenig.com"]


def titleize_key(value):
    return str(value).replace("_", " ").replace("-", " ").title()


def format_detail_rows(details, parent_key=""):
    if details is None:
        return []

    if isinstance(details, dict):
        rows = []
        for key, value in details.items():
            label = titleize_key(key)
            full_label = f"{parent_key} - {label}" if parent_key else label
            rows.extend(format_detail_rows(value, full_label))
        return rows

    if isinstance(details, list):
        rows = []
        for index, value in enumerate(details, start=1):
            label = f"{parent_key} {index}".strip()
            rows.extend(format_detail_rows(value, label))
        return rows

    return [{"label": parent_key or "Details", "value": details}]


def send_email(subject, html_content, recipient_list):
    plain_message = strip_tags(html_content)
    email = EmailMultiAlternatives(
        subject,
        plain_message,
        settings.EMAIL_HOST_USER,
        recipient_list,
    )
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)


class ReportClaim(CreateAPIView):
    queryset = Claim.objects.all()
    serializer_class = ClaimSerializer

    def perform_create(self, serializer):
        claim = serializer.save()
        html_content = render_to_string(
            "emails/claim_report.html", {"claim": claim})
        subject = f"New Claim Reported by {claim.email}"
        send_email(
            subject,
            html_content,
         TRAVEL_AGENCY_EMAILS,
        )
        print("Claim Reported Successfully")


class ContactMail(CreateAPIView):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer

    def perform_create(self, serializer):
        contact = serializer.save()
        html_content = render_to_string(
            "emails/contact_mail.html", {"contact": contact})
        subject = f"New Contact from {contact.first_name}"
        send_email(
            subject,
            html_content,
            TRAVEL_AGENCY_EMAILS,
        )
        print("Contact Mailed Successfully")


class NewsletterSubscription(CreateAPIView):
    queryset = NewsletterSubscription.objects.all()
    serializer_class = NewsletterSubscriptionSerializer

    def perform_create(self, serializer):
        email_address = serializer.validated_data["email"]
        html_content = render_to_string(
            "emails/newsletter_subscription.html", {"email": email_address}
        )
        subject = f"New Subscriber with email {email_address}"
        try:
            send_email(
                subject,
                html_content,
                TRAVEL_AGENCY_EMAILS,
            )
            print("Subscribed successfully")
            serializer.save()
        except Exception as e:
            print(f"Failed to send email: {e}")
            raise


class SubmitCv(CreateAPIView):
    queryset = SubmitCv.objects.all()
    serializer_class = SubmitCvSerializer

    def perform_create(self, serializer):
        cv_submission = serializer.save()
        html_content = render_to_string(
            "emails/submit_cv.html", {"cv": cv_submission})
        subject = f"New CV Submitted by {cv_submission.email}"
        send_email(
            subject,
            html_content,
            TRAVEL_AGENCY_EMAILS,
        )
        print("CV Submitted Successfully")


class RegisterUser(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializerWithToken

    def perform_create(self, serializer):
        user = serializer.save()
        user_html_content = render_to_string(
            "emails/account_welcome.html",
            {"user": user},
        )
        agency_html_content = render_to_string(
            "emails/new_user_registration.html",
            {"user": user},
        )
        send_email("Welcome to Thrive Travels", user_html_content, [user.email])
        send_email(
            f"New Thrive Travels User Registered - {user.email}",
            agency_html_content,
            TRAVEL_AGENCY_EMAILS,
        )



class UserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(
            request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FlightBookingAPIView(CreateAPIView):
    queryset = FlightBooking.objects.all()
    serializer_class = FlightBookingSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        booking = serializer.save(user=self.request.user)
        html_content = render_to_string(
            "emails/booking_confirmation.html",
            {
                "user": self.request.user,
                "user_details": booking.user_details,
                "user_detail_rows": format_detail_rows(booking.user_details),
                "flight_details": booking.flight_details,
                "flight_detail_rows": format_detail_rows(booking.flight_details),
                "booking_id": booking.id,
                "booking_date": booking.booking_date,
                "booking_type": "Flight",
                "is_agency_notification": True,
            },
        )
        send_email(
            f"New Thrive Travels Flight Booking #{booking.id}",
            html_content,
            TRAVEL_AGENCY_EMAILS,
        )


class HotelBookingAPIView(CreateAPIView):
    queryset = HotelBooking.objects.all()
    serializer_class = HotelBookingSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        booking = serializer.save(user=self.request.user)
        html_content = render_to_string(
            "emails/booking_confirmation.html",
            {
                "user": self.request.user,
                "user_details": booking.user_details,
                "user_detail_rows": format_detail_rows(booking.user_details),
                "hotel_details": booking.hotel_details,
                "hotel_detail_rows": format_detail_rows(booking.hotel_details),
                "booking_id": booking.id,
                "booking_date": booking.booking_date,
                "booking_type": "Hotel",
                "is_agency_notification": True,
            },
        )

        send_email(
            f"New Thrive Travels Hotel Booking #{booking.id}",
            html_content,
            TRAVEL_AGENCY_EMAILS,
        )
