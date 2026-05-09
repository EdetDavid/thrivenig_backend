from django.contrib import admin
from .models import Claim,  Contact, NewsletterSubscription, SubmitCv

# Register your models here.


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ('insured', 'policy_number', 'email', 'phone', 'file')
    search_fields = ('insured', 'policy_number', 'email', 'phone', 'file')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'email', 'phone', 'created_at')
    search_fields = ('first_name', 'email', 'phone')


@admin.register(NewsletterSubscription)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ('email',)
    search_fields = ('email',)


@admin.register(SubmitCv)
class SubmitCvAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'created_at')
    search_fields = ('name', 'email',)
