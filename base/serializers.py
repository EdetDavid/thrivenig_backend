from rest_framework import serializers
from .models import (
    Claim,
    Contact,
    NewsletterSubscription,
    SubmitCv,
    UserProfile,
    FlightBooking,
    HotelBooking,
)
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'


class NewsletterSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscription
        fields = ('email',)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class UserSerializerWithToken(serializers.ModelSerializer):
    token = serializers.SerializerMethodField(read_only=True)
    phone = serializers.CharField(source='profile.phone', allow_blank=True, required=False)
    address = serializers.CharField(source='profile.address', allow_blank=True, required=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "token", "first_name", "last_name", "phone", "address"]
        extra_kwargs = {"password": {"write_only": True, "required": True}}

    def get_token(self, obj):
        token, _ = Token.objects.get_or_create(user=obj)
        return token.key

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        user = User.objects.create_user(
            username=validated_data.get('username'),
            email=validated_data.get('email'),
            password=validated_data.get('password'),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        Token.objects.get_or_create(user=user)
        profile = UserProfile.objects.get_or_create(user=user)[0]
        profile.phone = profile_data.get('phone', '')
        profile.address = profile_data.get('address', '')
        profile.save()
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source='profile.phone', allow_blank=True, required=False)
    address = serializers.CharField(source='profile.address', allow_blank=True, required=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone", "address"]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        profile, _ = UserProfile.objects.get_or_create(user=instance)
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()
        return instance


class FlightBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = FlightBooking
        fields = ["id", "user", "user_details", "flight_details", "search_results", "booking_type", "booking_date"]
        read_only_fields = ["id", "user", "booking_type", "booking_date"]


class HotelBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = HotelBooking
        fields = ["id", "user", "user_details", "hotel_details", "search_results", "booking_type", "booking_date"]
        read_only_fields = ["id", "user", "booking_type", "booking_date"]


class SubmitCvSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmitCv
        fields = '__all__'
