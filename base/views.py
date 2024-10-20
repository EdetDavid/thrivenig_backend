
from .models import Contact, Claim, NewsletterSubscription, SubmitCv
from django.core.mail import EmailMessage

from rest_framework.generics import GenericAPIView
from rest_framework.mixins import CreateModelMixin, ListModelMixin

from .serializers import ClaimSerializer, ContactSerializer, NewsletterSubscriptionSerializer, SubmitCvSerializer

from django.conf import settings


from django.template.loader import render_to_string




class ReportClaim(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = Claim.objects.all()
    serializer_class = ClaimSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        claim = serializer.save()
        # Render email template with context
        subject = f'New Claim Reported by {claim.email}'
        context = {
            'claim': claim
        }
        message_html = render_to_string('emails/claim_report.html', context)

        email = EmailMessage(
            subject,
            message_html,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )
        email.content_subtype = "html"  # To send HTML email

        if claim.file:
            email.attach(claim.file.name, claim.file.read())

        email.send(fail_silently=False)
        print("Claim Reported Successfully")


class ContactMail(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        contact = serializer.save()
        # Render email template with context
        subject = f'New Contact from {contact.first_name}'
        context = {
            'contact': contact
        }
        message_html = render_to_string('emails/contact_mail.html', context)

        email = EmailMessage(
            subject,
            message_html,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )
        email.content_subtype = "html"  # To send HTML email

        email.send(fail_silently=False)
        print("Contact Mailed Successfully")


class NewsletterSubscription(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = NewsletterSubscription.objects.all()
    serializer_class = NewsletterSubscriptionSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        email = serializer.validated_data['email']
        # Render email template with context
        subject = f'New Subscriber with email {email}'
        context = {
            'email': email
        }
        message_html = render_to_string('emails/newsletter_subscription.html', context)

        email_message = EmailMessage(
            subject,
            message_html,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )
        email_message.content_subtype = "html"  # To send HTML email

        try:
            email_message.send(fail_silently=False)
            print("Subscribed successfully")
            serializer.save()  # Save the subscription after email is sent
        except Exception as e:
            print(f"Failed to send email: {e}")
            raise


class SubmitCv(GenericAPIView, CreateModelMixin, ListModelMixin):
    queryset = SubmitCv.objects.all()
    serializer_class = SubmitCvSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        cv_submission = serializer.save()
        # Render email template with context
        subject = f'New CV Submitted by {cv_submission.email}'
        context = {
            'cv_submission': cv_submission
        }
        message_html = render_to_string('emails/submit_cv.html', context)

        email = EmailMessage(
            subject,
            message_html,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )
        email.content_subtype = "html"  # To send HTML email

        if cv_submission.cv:
            email.attach(cv_submission.cv.name, cv_submission.cv.read())

        email.send(fail_silently=False)
        print("CV Submitted Successfully")

