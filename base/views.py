from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Contact, Claim, NewsletterSubscription, SubmitCv
from django.core.mail import EmailMultiAlternatives
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import CreateModelMixin, ListModelMixin
from .serializers import ClaimSerializer, ContactSerializer, NewsletterSubscriptionSerializer, SubmitCvSerializer
from django.conf import settings


class ReportClaim(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = Claim.objects.all()
    serializer_class = ClaimSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        claim = serializer.save()

        html_content = render_to_string(
            'emails/claim_report.html', {'claim': claim})
        plain_message = strip_tags(html_content)

        subject = f'New Claim Reported by {claim.email}'
        email = EmailMultiAlternatives(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,

            ['dvooskid12345@gmail.com', 'infoinsurance@thrivenig.com',
                'infotravels@thrivenig.com']
        )
        email.attach_alternative(html_content, "text/html")

        if claim.file:
            email.attach(claim.file.name, claim.file.read())

        email.send(fail_silently=False)
        print("Claim Reported Successfully")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class ContactMail(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        contact = serializer.save()

        html_content = render_to_string(
            'emails/contact_mail.html', {'contact': contact})
        plain_message = strip_tags(html_content)

        subject = f'New Contact from {contact.first_name}'
        email = EmailMultiAlternatives(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,

            ['dvooskid12345@gmail.com', 'infoinsurance@thrivenig.com',
                'infotravels@thrivenig.com']
        )
        email.attach_alternative(html_content, "text/html")

        email.send(fail_silently=False)
        print("Contact Mailed Successfully")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class NewsletterSubscription(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = NewsletterSubscription.objects.all()
    serializer_class = NewsletterSubscriptionSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        email_address = serializer.validated_data['email']

        html_content = render_to_string(
            'emails/newsletter_subscription.html', {'email': email_address})
        plain_message = strip_tags(html_content)

        subject = f'New Subscriber with email {email_address}'
        email = EmailMultiAlternatives(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,

            ['dvooskid12345@gmail.com', 'infoinsurance@thrivenig.com',
                'infotravels@thrivenig.com']
        )
        email.attach_alternative(html_content, "text/html")

        try:
            email.send(fail_silently=False)
            print("Subscribed successfully")
            serializer.save()
        except Exception as e:
            print(f"Failed to send email: {e}")
            raise

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


class SubmitCv(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = SubmitCv.objects.all()
    serializer_class = SubmitCvSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        cv_submission = serializer.save()

        html_content = render_to_string(
            'emails/submit_cv.html', {'cv': cv_submission})
        plain_message = strip_tags(html_content)

        subject = f'New CV Submitted by {cv_submission.email}'
        email = EmailMultiAlternatives(
            subject,
            plain_message,
            settings.EMAIL_HOST_USER,

            ['dvooskid12345@gmail.com', 'infoinsurance@thrivenig.com',
                'infotravels@thrivenig.com']
        )
        email.attach_alternative(html_content, "text/html")

        if cv_submission.cv:
            email.attach(cv_submission.cv.name, cv_submission.cv.read())

        email.send(fail_silently=False)
        print("CV Submitted Successfully")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)
