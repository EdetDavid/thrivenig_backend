
from .views import ReportClaim, ContactMail, NewsletterSubscription
from django.urls import path, include


urlpatterns = [
    path("report-claim/", ReportClaim.as_view(), name="report-claim"),
    path('contact/', ContactMail.as_view(), name='contact'),
    path('newsletter/', NewsletterSubscription.as_view(),
         name='newsletter-subscribe'),

]
