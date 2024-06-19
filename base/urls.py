from django.urls import path
from .views import ReportClaim, ContactMail, NewsletterSubscription, SubmitCv
from django.urls import path


urlpatterns = [
    path("report-claim/", ReportClaim.as_view(), name="report-claim"),
    path('contact/', ContactMail.as_view(), name='contact'),
    path('newsletter/', NewsletterSubscription.as_view(),
         name='newsletter-subscribe'),
    path('submit-cv/', SubmitCv.as_view(), name='submit_cv'),

]
