from django.db import models


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
    phone = models.CharField(max_length=20)  # Changed from subject to phone
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
