from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
import json
import logging
from time import perf_counter
from urllib import error, request as url_request
from rest_framework.generics import (
    CreateAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from .models import (
    Contact,
    Claim,
    NewsletterSubscription,
    SubmitCv,
    FlightBooking,
    HotelBooking,
    HotelListing,
    TravelPricingSettings,
    TravelSearchLog,
    UserProfile,
)
from .permissions import IsActiveSuperuser
from .serializers import (
    ClaimSerializer,
    ContactSerializer,
    NewsletterSubscriptionSerializer,
    SubmitCvSerializer,
    UserSerializerWithToken,
    UserProfileSerializer,
    FlightBookingSerializer,
    FlightLocationQuerySerializer,
    FlightSearchSerializer,
    HotelBookingSerializer,
    HotelLocationQuerySerializer,
    HotelSearchSerializer,
    TravelAdminFlightRequestSerializer,
    TravelAdminHotelListingSerializer,
    TravelAdminHotelRequestSerializer,
    TravelAdminUserRoleSerializer,
    TravelAdminUserSerializer,
    TravelPricingSettingsSerializer,
    TravelSearchLogSerializer,
)
from .services.flight_search import (
    FlightSearchNotConfigured,
    FlightSearchProviderError,
    FlightSearchTimeout,
    FlightSearchValidationError,
    search_flight_locations,
    search_flights,
)
from .services.hotel_search import (
    HotelSearchNotConfigured,
    HotelSearchPermissionError,
    HotelSearchProviderError,
    HotelSearchTimeout,
    HotelSearchValidationError,
    provider_display_name,
    search_hotel_locations,
    search_hotels,
)
from .services.search_logging import record_travel_search
from .services.travel_pricing import TravelPricingError

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


def send_email(subject, html_content, recipient_list, *, reply_to=None):
    plain_message = strip_tags(html_content)
    email = EmailMultiAlternatives(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list,
        reply_to=reply_to,
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
            settings.INSURANCE_AGENCY_EMAILS,
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
            settings.ADMIN_EMAILS,
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
                settings.ADMIN_EMAILS,
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
            settings.ADMIN_EMAILS,
        )
        print("CV Submitted Successfully")


class RegisterUser(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializerWithToken

    def perform_create(self, serializer):
        user = serializer.save()
        registration_site = serializer.validated_data.get('site', 'travel')
        is_insurance = registration_site == 'insurance'
        user_html_content = render_to_string(
            (
                "emails/insurance_account_welcome.html"
                if is_insurance
                else "emails/account_welcome.html"
            ),
            {"user": user},
        )
        agency_html_content = render_to_string(
            (
                "emails/insurance_new_user_registration.html"
                if is_insurance
                else "emails/new_user_registration.html"
            ),
            {"user": user},
        )
        brand_name = 'Thrive Insurance' if is_insurance else 'Thrive Travels'
        agency_recipients = (
            settings.INSURANCE_AGENCY_EMAILS
            if is_insurance
            else settings.ADMIN_EMAILS
        )
        send_email(f"Welcome to {brand_name}", user_html_content, [user.email])
        send_email(
            f"New {brand_name} User Registered - {user.email}",
            agency_html_content,
            agency_recipients,
        )


class LoginAPIView(ObtainAuthToken):
    """Return the token and canonical dashboard role in one response."""

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        UserProfile.objects.get_or_create(user=user)

        return Response(
            {
                'token': token.key,
                'user': UserProfileSerializer(user).data,
            }
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


class FlightSearchAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "flight_search"

    def post(self, request):
        serializer = FlightSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        criteria = serializer.validated_data
        started_at = perf_counter()

        def log_search(log_status, *, results=None, error_code=''):
            record_travel_search(
                request=request,
                service_type=TravelSearchLog.SERVICE_FLIGHT,
                criteria=criteria,
                status=log_status,
                duration_ms=round((perf_counter() - started_at) * 1000),
                results=results,
                provider=settings.FLIGHT_SEARCH_PROVIDER.strip(),
                error_code=error_code,
            )

        try:
            results = search_flights(criteria)
        except FlightSearchNotConfigured as exc:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                error_code='FLIGHT_SEARCH_NOT_CONFIGURED',
            )
            return Response(
                {
                    "code": "FLIGHT_SEARCH_NOT_CONFIGURED",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except FlightSearchTimeout as exc:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                error_code='FLIGHT_SEARCH_TIMEOUT',
            )
            return Response(
                {
                    "code": "FLIGHT_SEARCH_TIMEOUT",
                    "detail": str(exc),
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except FlightSearchValidationError as exc:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                error_code='FLIGHT_SEARCH_INVALID',
            )
            return Response(
                {
                    "code": "FLIGHT_SEARCH_INVALID",
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FlightSearchProviderError as exc:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                error_code='FLIGHT_SEARCH_PROVIDER_ERROR',
            )
            return Response(
                {
                    "code": "FLIGHT_SEARCH_PROVIDER_ERROR",
                    "detail": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        log_search(TravelSearchLog.STATUS_SUCCESS, results=results)
        return Response(results)


class FlightLocationAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "flight_locations"

    def get(self, request):
        serializer = FlightLocationQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        try:
            results = search_flight_locations(serializer.validated_data["query"])
        except FlightSearchNotConfigured as exc:
            return Response(
                {
                    "code": "FLIGHT_SEARCH_NOT_CONFIGURED",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except FlightSearchTimeout as exc:
            return Response(
                {
                    "code": "FLIGHT_SEARCH_TIMEOUT",
                    "detail": str(exc),
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except FlightSearchValidationError as exc:
            return Response(
                {
                    "code": "FLIGHT_SEARCH_INVALID",
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except FlightSearchProviderError as exc:
            return Response(
                {
                    "code": "FLIGHT_SEARCH_PROVIDER_ERROR",
                    "detail": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(results)


def _hotel_log_criteria(payload):
    if not isinstance(payload, dict):
        return {}
    allowed_fields = {
        'destination',
        'city',
        'checkInDate',
        'checkOutDate',
        'rooms',
        'adults',
        'childAges',
        'guests',
        'radiusKm',
        'freeCancellationOnly',
        'roomType',
    }
    return {
        key: value
        for key, value in payload.items()
        if key in allowed_fields
        and isinstance(value, (str, int, float, bool, list, dict))
    }


def _hotel_error_response(exc, *, operation='search'):
    if isinstance(exc, HotelSearchNotConfigured):
        return (
            'HOTEL_SEARCH_NOT_CONFIGURED',
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, HotelSearchTimeout):
        return 'HOTEL_SEARCH_TIMEOUT', status.HTTP_504_GATEWAY_TIMEOUT
    if isinstance(exc, HotelSearchValidationError):
        return 'HOTEL_SEARCH_INVALID', status.HTTP_400_BAD_REQUEST
    if isinstance(exc, HotelSearchPermissionError):
        return (
            'HOTEL_SEARCH_PERMISSION_ERROR',
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, HotelSearchProviderError):
        return 'HOTEL_SEARCH_PROVIDER_ERROR', status.HTTP_502_BAD_GATEWAY
    logger.error('Unexpected hotel %s error: %s', operation, exc.__class__.__name__)
    return 'HOTEL_SEARCH_PROVIDER_ERROR', status.HTTP_502_BAD_GATEWAY


class HotelLocationAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'hotel_locations'

    def get(self, request):
        serializer = HotelLocationQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            results = search_hotel_locations(serializer.validated_data['query'])
        except (
            HotelSearchNotConfigured,
            HotelSearchTimeout,
            HotelSearchValidationError,
            HotelSearchPermissionError,
            HotelSearchProviderError,
        ) as exc:
            code, response_status = _hotel_error_response(
                exc,
                operation='location search',
            )
            return Response(
                {'code': code, 'detail': str(exc)},
                status=response_status,
            )
        return Response(results)


class HotelSearchAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'hotel_search'

    def post(self, request):
        started_at = perf_counter()
        serializer = HotelSearchSerializer(data=request.data)

        def log_search(log_status, *, criteria, results=None, error_code=''):
            record_travel_search(
                request=request,
                service_type=TravelSearchLog.SERVICE_HOTEL,
                criteria=criteria,
                status=log_status,
                duration_ms=round((perf_counter() - started_at) * 1000),
                results=results,
                provider=provider_display_name(),
                error_code=error_code,
            )

        if not serializer.is_valid():
            log_search(
                TravelSearchLog.STATUS_FAILED,
                criteria=_hotel_log_criteria(request.data),
                error_code='HOTEL_SEARCH_INVALID',
            )
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        criteria = serializer.validated_data
        try:
            results = search_hotels(criteria)
        except (
            HotelSearchNotConfigured,
            HotelSearchTimeout,
            HotelSearchValidationError,
            HotelSearchPermissionError,
            HotelSearchProviderError,
        ) as exc:
            code, response_status = _hotel_error_response(exc)
            log_search(
                TravelSearchLog.STATUS_FAILED,
                criteria=criteria,
                error_code=code,
            )
            return Response(
                {'code': code, 'detail': str(exc)},
                status=response_status,
            )
        except TravelPricingError:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                criteria=criteria,
                error_code='HOTEL_SEARCH_PRICING_ERROR',
            )
            logger.exception('Hotel inventory pricing failed')
            return Response(
                {
                    'code': 'HOTEL_SEARCH_PRICING_ERROR',
                    'detail': 'Hotel prices are temporarily unavailable.',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            log_search(
                TravelSearchLog.STATUS_FAILED,
                criteria=criteria,
                error_code='HOTEL_SEARCH_INTERNAL_ERROR',
            )
            raise

        log_search(
            TravelSearchLog.STATUS_SUCCESS,
            criteria=criteria,
            results=results,
        )
        return Response(results)


class FlightBookingAPIView(CreateAPIView):
    queryset = FlightBooking.objects.all()
    serializer_class = FlightBookingSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "flight_booking"

    def perform_create(self, serializer):
        account = self.request.user if self.request.user.is_authenticated else None
        booking = serializer.save(user=account)
        customer_name = booking.guest_name
        customer_email = booking.guest_email
        customer_phone = booking.guest_phone
        if account:
            customer_name = customer_name or account.get_full_name() or account.username
            customer_email = customer_email or account.email
            customer_phone = customer_phone or getattr(
                getattr(account, 'profile', None),
                'phone',
                '',
            )

        html_content = render_to_string(
            "emails/flight_request.html",
            {
                "account": account,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "customer_phone": customer_phone,
                "user_detail_rows": format_detail_rows(booking.user_details),
                "flight_detail_rows": format_detail_rows(booking.flight_details),
                "offer_detail_rows": format_detail_rows(booking.search_results),
                "booking_reference": f"TTF-{booking.id:06d}",
                "booking_date": booking.booking_date,
            },
        )
        try:
            send_email(
                f"New Thrive Travels Flight Request TTF-{booking.id:06d}",
                html_content,
                settings.TRAVEL_AGENCY_EMAILS,
                reply_to=[customer_email] if customer_email else None,
            )
        except Exception:
            # The request is already safely persisted. Returning 201 prevents a
            # retry from creating duplicates; operations can recover from logs/admin.
            logger.exception(
                "Flight request notification failed for booking %s",
                booking.id,
            )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = {
            **response.data,
            "message": (
                "Your fare request has been received. Availability and final "
                "price will be confirmed before payment."
            ),
        }
        return response


class HotelBookingAPIView(CreateAPIView):
    queryset = HotelBooking.objects.select_related('listing', 'user')
    serializer_class = HotelBookingSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'hotel_booking'

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

        try:
            send_email(
                f"New Thrive Travels Hotel Booking #{booking.id}",
                html_content,
                settings.TRAVEL_AGENCY_EMAILS,
            )
        except Exception:
            logger.exception(
                'Hotel request notification failed for booking %s',
                booking.id,
            )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = {
            **response.data,
            'message': (
                'Your hotel request has been received. Availability and final '
                'price will be confirmed.'
            ),
        }
        return response


class TravelAdminPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class TravelAdminHotelListingListAPIView(ListCreateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminHotelListingSerializer
    pagination_class = TravelAdminPagination

    def get_queryset(self):
        queryset = HotelListing.objects.all().order_by('-updated_at', '-id')
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(city__icontains=query)
                | Q(country__icontains=query)
                | Q(room_type__icontains=query)
            )
        city = self.request.query_params.get('city', '').strip()
        if city:
            queryset = queryset.filter(city__iexact=city)
        for field_name in ('active', 'test_data'):
            value = self.request.query_params.get(field_name, '').strip().lower()
            if value in {'true', 'false'}:
                queryset = queryset.filter(
                    **{field_name: value == 'true'}
                )
        return queryset


class TravelAdminHotelListingDetailAPIView(RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminHotelListingSerializer
    queryset = HotelListing.objects.all()
    http_method_names = ['get', 'patch', 'head', 'options']


class TravelAdminOverviewAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        today = timezone.localdate()
        pricing = TravelPricingSettings.load()
        return Response(
            {
                'totals': {
                    'users': User.objects.count(),
                    'active_users': User.objects.filter(is_active=True).count(),
                    'flight_searches': TravelSearchLog.objects.filter(
                        service_type=TravelSearchLog.SERVICE_FLIGHT,
                    ).count(),
                    'hotel_searches': TravelSearchLog.objects.filter(
                        service_type=TravelSearchLog.SERVICE_HOTEL,
                    ).count(),
                    'flight_requests': FlightBooking.objects.count(),
                    'hotel_requests': HotelBooking.objects.count(),
                    'pending_flight_requests': FlightBooking.objects.filter(
                        status=FlightBooking.STATUS_PENDING,
                    ).count(),
                    'pending_hotel_requests': HotelBooking.objects.filter(
                        status=HotelBooking.STATUS_PENDING,
                    ).count(),
                },
                'today': {
                    'flight_searches': TravelSearchLog.objects.filter(
                        service_type=TravelSearchLog.SERVICE_FLIGHT,
                        created_at__date=today,
                    ).count(),
                    'hotel_searches': TravelSearchLog.objects.filter(
                        service_type=TravelSearchLog.SERVICE_HOTEL,
                        created_at__date=today,
                    ).count(),
                    'flight_requests': FlightBooking.objects.filter(
                        booking_date__date=today,
                    ).count(),
                    'hotel_requests': HotelBooking.objects.filter(
                        booking_date__date=today,
                    ).count(),
                },
                'pricing': TravelPricingSettingsSerializer(pricing).data,
            }
        )


class TravelPricingSettingsAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        serializer = TravelPricingSettingsSerializer(
            TravelPricingSettings.load()
        )
        return Response(serializer.data)

    def patch(self, request):
        pricing = TravelPricingSettings.load()
        serializer = TravelPricingSettingsSerializer(
            pricing,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)


class TravelAdminUserListAPIView(ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminUserSerializer
    pagination_class = TravelAdminPagination

    def get_queryset(self):
        queryset = User.objects.select_related('profile').prefetch_related(
            'groups'
        ).annotate(
            flight_request_count=Count('flight_bookings', distinct=True),
            hotel_request_count=Count('hotel_bookings', distinct=True),
            search_count=Count('travel_searches', distinct=True),
        ).order_by('-date_joined', '-id')
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        return queryset


class TravelAdminUserRoleAPIView(RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser, IsActiveSuperuser]
    serializer_class = TravelAdminUserRoleSerializer
    http_method_names = ['patch', 'head', 'options']

    def get_queryset(self):
        return User.objects.select_related('profile').prefetch_related(
            'groups'
        ).annotate(
            flight_request_count=Count('flight_bookings', distinct=True),
            hotel_request_count=Count('hotel_bookings', distinct=True),
            search_count=Count('travel_searches', distinct=True),
        )

    @transaction.atomic
    def perform_update(self, serializer):
        updated_user = serializer.save()
        role_change = getattr(updated_user, '_role_change', None)
        if role_change:
            previous_role, new_role = role_change
            change_message = {
                ('traveler', 'admin'): (
                    'Granted travel admin dashboard access.'
                ),
                ('content_manager', 'admin'): (
                    'Granted travel admin dashboard access.'
                ),
                ('admin', 'traveler'): (
                    'Revoked travel admin dashboard access.'
                ),
                ('admin', 'content_manager'): (
                    'Changed dashboard access from administrator to content '
                    'manager.'
                ),
                ('traveler', 'content_manager'): (
                    'Granted content manager dashboard access.'
                ),
                ('content_manager', 'traveler'): (
                    'Revoked content manager dashboard access.'
                ),
            }[role_change]
            LogEntry.objects.log_actions(
                user_id=self.request.user.pk,
                queryset=[updated_user],
                action_flag=CHANGE,
                change_message=change_message,
                single_object=True,
            )
            logger.info(
                'Dashboard role changed from %s to %s: actor_id=%s target_id=%s',
                previous_role,
                new_role,
                self.request.user.pk,
                updated_user.pk,
            )


class TravelAdminSearchListAPIView(ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelSearchLogSerializer
    pagination_class = TravelAdminPagination
    service_type = None

    def get_queryset(self):
        queryset = TravelSearchLog.objects.select_related('user').filter(
            service_type=self.service_type,
        )
        search_status = self.request.query_params.get('status', '').strip().lower()
        if search_status:
            queryset = queryset.filter(status=search_status)
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(provider__icontains=query)
                | Q(provider_reference__icontains=query)
                | Q(error_code__icontains=query)
                | Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
            )
        return queryset


class TravelAdminFlightSearchListAPIView(TravelAdminSearchListAPIView):
    service_type = TravelSearchLog.SERVICE_FLIGHT


class TravelAdminHotelSearchListAPIView(TravelAdminSearchListAPIView):
    service_type = TravelSearchLog.SERVICE_HOTEL


class TravelAdminFlightRequestListAPIView(ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminFlightRequestSerializer
    pagination_class = TravelAdminPagination

    def get_queryset(self):
        queryset = FlightBooking.objects.select_related('user').order_by(
            '-booking_date',
            '-id',
        )
        request_status = self.request.query_params.get('status', '').strip().lower()
        if request_status:
            queryset = queryset.filter(status=request_status)
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(guest_name__icontains=query)
                | Q(guest_email__icontains=query)
                | Q(guest_phone__icontains=query)
                | Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
            )
        return queryset


class TravelAdminHotelRequestListAPIView(ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminHotelRequestSerializer
    pagination_class = TravelAdminPagination

    def get_queryset(self):
        queryset = HotelBooking.objects.select_related('user').order_by(
            '-booking_date',
            '-id',
        )
        request_status = self.request.query_params.get('status', '').strip().lower()
        if request_status:
            queryset = queryset.filter(status=request_status)
        query = self.request.query_params.get('q', '').strip()
        if query:
            queryset = queryset.filter(
                Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
            )
        return queryset


class TravelAdminFlightRequestDetailAPIView(RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminFlightRequestSerializer
    queryset = FlightBooking.objects.select_related('user')
    http_method_names = ['get', 'patch', 'head', 'options']


class TravelAdminHotelRequestDetailAPIView(RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = TravelAdminHotelRequestSerializer
    queryset = HotelBooking.objects.select_related('user')
    http_method_names = ['get', 'patch', 'head', 'options']
