
from .models import Contact, Claim, NewsletterSubscription, SubmitCv
from django.core.mail import EmailMessage

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
        # Send email
        subject = f'New Claim Reported by {claim.email}'
        message = f"Insured: {claim.insured}\nPolicy Number: {claim.policy_number}\nEmail: {claim.email}\nPhone: {claim.phone}"

        email = EmailMessage(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )

        if claim.file:
            email.attach(claim.file.name, claim.file.read(),

                         )

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
        # Send email
        subject = f'New Contact from {contact.first_name}'
        message = f"Name: {contact.first_name}\nEmail: {contact.email}\nPhone: {contact.phone}\n Message: {contact.message}"

        email = EmailMessage(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )

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
        email = serializer.validated_data['email']

        subject = f'New Subscriber with email {email}'
        message = f"{email} \t just subscribed to our newsletter"

        email_message = EmailMessage(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )

        try:
            email_message.send(fail_silently=False)
            print("Subscribed successfully")
            serializer.save()  # Save the subscription after email is sent
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
        # Send email
        subject = f'New CV Submitted by {cv_submission.email}'
        message = f"Name: {cv_submission.name}\nEmail: {cv_submission.email}\nCover Letter: {cv_submission.cover_letter}"

        email = EmailMessage(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            ['dvooskid12345@gmail.com']  # Replace with the recipient's email
        )

        if cv_submission.cv:
            email.attach(cv_submission.cv.name, cv_submission.cv.read())

        email.send(fail_silently=False)
        print("CV Submitted Successfully")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)
