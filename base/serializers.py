
from rest_framework import serializers
from .models import Claim, Contact, NewsletterSubscription, SubmitCv

from django.contrib.auth.models import User
from rest_framework.authtoken.views import Token


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'

# serializers.py


class NewsletterSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscription
        fields = ('email',)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

        extra_kwargs = {"password": {"write_only": True, "required": True}}

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        Token.objects.create(user=user)
        return user


class SubmitCvSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmitCv
        fields = '__all__'
