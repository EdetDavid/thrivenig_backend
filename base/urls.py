from django.urls import path
from .views import (
    ReportClaim,
    ContactMail,
    NewsletterSubscription,
    SubmitCv,
    RegisterUser,
    UserProfileAPIView,
    FlightBookingAPIView,
    HotelBookingAPIView,
)

urlpatterns = [
    path("report-claim/", ReportClaim.as_view(), name="report-claim"),
    path('contact/', ContactMail.as_view(), name='contact'),
    path('newsletter/', NewsletterSubscription.as_view(), name='newsletter-subscribe'),
    path('submit-cv/', SubmitCv.as_view(), name='submit_cv'),
    path('users/', RegisterUser.as_view(), name='register'),
    path('profile/', UserProfileAPIView.as_view(), name='profile'),
    path('flight-bookings/', FlightBookingAPIView.as_view(), name='flight-bookings'),
    path('hotel-bookings/', HotelBookingAPIView.as_view(), name='hotel-bookings'),
]
