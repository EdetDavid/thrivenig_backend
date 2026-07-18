from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.models import User
from django.conf import settings
import json
import logging
from urllib import error, request as url_request
from rest_framework.generics import CreateAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
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
logger = logging.getLogger(__name__)

THRIVE_CHATBOT_INSTRUCTIONS = """
You are the warm, concise virtual guide for Thrive Holdings Limited, a Nigerian
holding company. Be conversational, ask only one useful follow-up question at a
time, and use the guest's first name if they provide it.

Website facts:
- Thrive Holdings provides strategic direction, governance, and shared support.
- Its operating companies are Thrive Insurance Brokers Limited and Thrive
  Travels & Tours Limited.
- Insurance supports risk advice, policy placement, renewals, and claims for
  individuals and organisations. Cover includes life, property, motor,
  liability, engineering, pecuniary, travel, marine, oil & gas, and specialty.
- Travel supports flights, hotels, visa assistance, tours, holidays, itineraries,
  and corporate travel management.
- Phone numbers: 08180996418 and 07087943708.
- Emails: infoinsurance@thrivenig.com and infotravels@thrivenig.com.

Rules:
- Never invent prices, quotes, availability, policy terms, claim outcomes, visa
  requirements, or booking confirmations.
- Do not request passport numbers, payment-card information, passwords, medical
  records, or other highly sensitive information in chat.
- For travel planning, naturally collect destination, approximate dates, number
  of travellers, and needed services. Then recommend the live WhatsApp or Tawk.to
  handoff available in the chat interface.
- For insurance claims or detailed advice, acknowledge the situation and refer
  the guest to a human agent.
- If the question is unrelated to Thrive, briefly explain what you can help with.
- Keep most answers under 100 words and do not use markdown tables.
""".strip()


def extract_response_text(payload):
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"].strip()
    return ""


class ChatbotAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chatbot"

    def post(self, request):
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            return Response(
                {"detail": "AI chat is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        raw_messages = request.data.get("messages", [])
        if not isinstance(raw_messages, list) or not raw_messages:
            return Response(
                {"detail": "A non-empty messages list is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        messages = []
        for item in raw_messages[-12:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content", "")).strip()[:1500]
            if content:
                messages.append({"role": item["role"], "content": content})

        if not messages or messages[-1]["role"] != "user":
            return Response(
                {"detail": "The latest valid message must be from the user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        body = json.dumps({
            "model": settings.OPENAI_CHAT_MODEL,
            "instructions": THRIVE_CHATBOT_INSTRUCTIONS,
            "input": messages,
            "max_output_tokens": 250,
            "reasoning": {"effort": "low"},
            "text": {"verbosity": "low"},
        }).encode("utf-8")
        api_request = url_request.Request(
            "https://api.openai.com/v1/responses",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with url_request.urlopen(api_request, timeout=25) as api_response:
                payload = json.loads(api_response.read().decode("utf-8"))
            answer = extract_response_text(payload)
            if not answer:
                raise ValueError("OpenAI returned no response text")
            return Response({"reply": answer})
        except (error.URLError, error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError):
            logger.exception("OpenAI chatbot request failed")
            return Response(
                {"detail": "The AI assistant is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


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
