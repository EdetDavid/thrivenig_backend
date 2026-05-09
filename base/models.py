from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Claim(models.Model):
    insured = models.CharField(max_length=100)
    policy_number = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    file = models.FileField(upload_to='uploads/', blank=True, null=True)

    def __str__(self):
        return self.policy_number


class Contact(models.Model):
    first_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} - {self.phone}"


class NewsletterSubscription(models.Model):
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email


class SubmitCv(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    cv = models.FileField(upload_to='cvs/')
    cover_letter = models.CharField(max_length=2500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.user.username


class FlightBooking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='flight_bookings')
    user_details = models.JSONField(blank=True, null=True)
    flight_details = models.JSONField()
    search_results = models.JSONField(blank=True, null=True)
    booking_type = models.CharField(max_length=20, default='flight')
    booking_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Flight booking #{self.id} for {self.user.username}"


class HotelBooking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hotel_bookings')
    user_details = models.JSONField(blank=True, null=True)
    hotel_details = models.JSONField()
    search_results = models.JSONField(blank=True, null=True)
    booking_type = models.CharField(max_length=20, default='hotel')
    booking_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Hotel booking #{self.id} for {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
