import logging

from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from core.models import User

logger = logging.getLogger(__name__)


class PublicUserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(
        max_length=254, required=True, allow_blank=False, allow_null=False
    )
    whatsapp = PhoneNumberField(required=True, allow_blank=False, allow_null=False)
    password = serializers.CharField()
    phone = serializers.CharField(min_length=7, max_length=20,required=False)
    first_name = serializers.CharField(min_length=2, max_length=50)
    last_name = serializers.CharField(min_length=2, max_length=50)

    def validate_email(self, data):
        email = data.lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("User with email already exists!")
        return email

    def validate_whatsapp(self, data):
        if User.objects.filter(whatsapp=data).exists():
            raise serializers.ValidationError("User with WhatsApp number already exists!")
        return data

    def validate_phone(self, data):
        phone = data
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("User with phone already exists!")
        return data

    def create(self, validated_data, *args, **kwargs):
        email = validated_data["email"].lower()
        whatsapp = validated_data["whatsapp"]
        phone = validated_data.get("phone",None)
        first_name = validated_data["first_name"]
        last_name = validated_data["last_name"]
        password = validated_data["password"]

        user = User.objects.create(
            email=email,
            username=email,
            whatsapp=whatsapp,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        user.set_password(password)
        user.save()
        logger.debug(f"Created new user: {user}")
        return user
