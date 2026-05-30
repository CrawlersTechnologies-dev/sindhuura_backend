from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from backend.models import Caste, SubscriptionPlan
from auth_api.models import MatrimonyProfile
from auth_api.models import CustomUser as User
from .models import *
from django.utils import timezone
import pytz
from backend.models import Blog
import re

def format_phone_number(phone_number):
    """
    Format Indian phone number to +91XXXXXXXXXX format
    Returns formatted phone or None if invalid
    """
    if not phone_number:
        return None
    
    # Remove any spaces and dashes
    phone = re.sub(r'[\s\-]', '', str(phone_number))
    
    # If it starts with +91 and is correct length
    if phone.startswith('+91') and len(phone) == 13:
        return phone
    
    # If it starts with 91 (without +)
    if phone.startswith('91') and len(phone) == 12:
        return f"+{phone}"
    
    # If it's 10 digits, add +91
    if len(phone) == 10 and phone[0] in '6789':
        return f"+91{phone}"
    
    return None

class RegisterSerializer(serializers.Serializer):

    # 🔐 USER FIELDS
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    phone_number = serializers.CharField(required=True, allow_blank=False)
    name = serializers.CharField(required=False, allow_blank=True)

    profile_image = serializers.ImageField(required=False, allow_null=True)
    aadhaar_card = serializers.FileField(required=False, allow_null=True)

    # 🧍 MATRIMONY PROFILE FIELDS
    this_account_for = serializers.ChoiceField(
        choices=MatrimonyProfile.ACCOUNT_FOR_CHOICES
    )
    mother_tongue = serializers.CharField()

    gender = serializers.ChoiceField(
        choices=MatrimonyProfile.GENDER_CHOICES
    )

    date_of_birth = serializers.DateField()
    height = serializers.CharField()

    physical_status = serializers.ChoiceField(
        choices=MatrimonyProfile.PHYSICAL_STATUS_CHOICES
    )
    marital_status = serializers.ChoiceField(
        choices=MatrimonyProfile.MARITAL_STATUS_CHOICES
    )

    children_count = serializers.IntegerField(
        required=False, allow_null=True
    )
    children_with_me = serializers.BooleanField(
        required=False, allow_null=True
    )

    religion = serializers.PrimaryKeyRelatedField(
        queryset=Caste.objects.filter(level="religion")
    )

    caste = serializers.PrimaryKeyRelatedField(
        queryset=Caste.objects.filter(level="caste"),
        required=False,
        allow_null=True
    )

    sub_caste = serializers.CharField(
        required=False, allow_blank=True
    )
    willing_inter_caste = serializers.BooleanField()

    education = serializers.ChoiceField(
        choices=MatrimonyProfile.EDUCATION_CHOICES
    )
    field_of_study = serializers.CharField()

    occupation = serializers.ChoiceField(
        choices=MatrimonyProfile.OCCUPATION_CHOICES
    )
    annual_income = serializers.ChoiceField(
        choices=MatrimonyProfile.INCOME_CHOICES
    )
    job_type = serializers.ChoiceField(
        choices=MatrimonyProfile.JOB_TYPE_CHOICES,
        required=False,
        allow_blank=True
    )

    country = serializers.CharField()
    state = serializers.CharField()
    city = serializers.CharField()

    family_status = serializers.ChoiceField(
        choices=MatrimonyProfile.FAMILY_STATUS_CHOICES
    )
    family_worth = serializers.ChoiceField(
        choices=MatrimonyProfile.FAMILY_WORTH_CHOICES
    )

    description = serializers.CharField(
        required=False, allow_blank=True
    )

    terms_accepted = serializers.BooleanField()

    # ✅ VALIDATIONS
    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match")

        if not data["terms_accepted"]:
            raise serializers.ValidationError(
                "You must accept terms & conditions"
            )

        # Format and validate phone number
        formatted_phone = format_phone_number(data["phone_number"])
        if not formatted_phone:
            raise serializers.ValidationError(
                "Invalid phone number format"
            )
        data["phone_number"] = formatted_phone

        if User.objects.filter(email=data["email"], is_deleted=False).exists():
            raise serializers.ValidationError(
                "Email already registered"
            )

        if User.objects.filter(phone_number=data["phone_number"], is_deleted=False).exists():
            raise serializers.ValidationError(
                "Phone number already registered"
            )

        if (
            data["marital_status"] != "never_married"
            and data.get("children_count") is None
        ):
            raise serializers.ValidationError(
                "Children count required for married profiles"
            )

        return data

    # 🔥 ATOMIC CREATE
    
    @transaction.atomic
    def create(self, validated_data):

        # Remove non-model fields
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        # Pop USER-ONLY fields
        profile_image = validated_data.pop("profile_image", None)
        aadhaar_card = validated_data.pop("aadhaar_card", None)

        # Create USER
        user = User.objects.create_user(
            email=validated_data.pop("email"),
            password=password,
            phone_number=validated_data.pop("phone_number", None),
            name=validated_data.pop("name", None),
            is_active=True,
        )

        # Save files
        if profile_image:
            user.profile_image = profile_image
        if aadhaar_card:
            user.aadhaar_card = aadhaar_card

        user.save()

        # Create MATRIMONY PROFILE
        profile = MatrimonyProfile.objects.create(
            user=user,
            **validated_data
        )

        return user, profile



class PersonalLifestyleSerializer(serializers.ModelSerializer):

    music_genres = serializers.PrimaryKeyRelatedField(
        queryset=MusicGenre.objects.all(),
        many=True,
        required=False
    )
    music_activities = serializers.PrimaryKeyRelatedField(
        queryset=MusicActivity.objects.all(),
        many=True,
        required=False
    )
    reading_preferences = serializers.PrimaryKeyRelatedField(
        queryset=ReadingPreference.objects.all(),
        many=True,
        required=False
    )
    movie_tv_genres = serializers.PrimaryKeyRelatedField(
        queryset=MovieGenre.objects.all(),
        many=True,
        required=False
    )

    class Meta:
        model = PersonalLifestyle
        exclude = ("profile",)

    @transaction.atomic
    def create(self, validated_data):
        profile = self.context["profile"]

        m2m_fields = {
            "music_genres": validated_data.pop("music_genres", []),
            "music_activities": validated_data.pop("music_activities", []),
            "reading_preferences": validated_data.pop("reading_preferences", []),
            "movie_tv_genres": validated_data.pop("movie_tv_genres", []),
        }

        lifestyle, _ = PersonalLifestyle.objects.update_or_create(
            profile=profile,
            defaults=validated_data
        )

        for field, values in m2m_fields.items():
            getattr(lifestyle, field).set(values)

        return lifestyle
    
class BaseNameSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ("id", "name")

class MusicGenreSerializer(BaseNameSerializer):
    class Meta(BaseNameSerializer.Meta):
        model = MusicGenre


class MusicActivitySerializer(BaseNameSerializer):
    class Meta(BaseNameSerializer.Meta):
        model = MusicActivity


class ReadingPreferenceSerializer(BaseNameSerializer):
    class Meta(BaseNameSerializer.Meta):
        model = ReadingPreference


class MovieGenreSerializer(BaseNameSerializer):
    class Meta(BaseNameSerializer.Meta):
        model = MovieGenre


class SubscriptionPlanSerializer(serializers.ModelSerializer):

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "plan_name",
            "price",
            "validity",
            "description",
            "is_active",
        ]


# images 
class MultipleImageUploadSerializer(serializers.Serializer):
    images = serializers.ListField(
        child=serializers.ImageField(),
        allow_empty=False
    )


# religion 
class ReligionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caste
        fields = ["id", "name"]

# caste
class CasteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caste
        fields = ["id", "name"]

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(
        source="subscription.plan_name",
        read_only=True
    )

    class Meta:
        model = SubscriptionPayment
        fields = (
            "id",
            "plan_name",
            "amount",
            "payment_method",
            "payment_status",
            "transaction_id",
            "paid_at",
            "created_at",
        )



    
# user profile serializer

class UserProfileSerializer(serializers.ModelSerializer):
    profile_image = serializers.SerializerMethodField()
    unique_id = serializers.CharField(read_only=True)
    class Meta:
        model = CustomUser
        fields = ("name", "address", "profile_image","unique_id")

    def get_profile_image(self, obj):
        request = self.context.get("request")

        if obj.profile_image:
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url

        return None

class FetchPersonalLifestyleSerializer(serializers.ModelSerializer):
    # 🔹 READ (GET → id + name)
    music_genres = MusicGenreSerializer(many=True, read_only=True)
    music_activities = MusicActivitySerializer(many=True, read_only=True)
    reading_preferences = ReadingPreferenceSerializer(many=True, read_only=True)
    movie_tv_genres = MovieGenreSerializer(many=True, read_only=True)

    # 🔹 WRITE (PATCH → IDs)
    music_genre_ids = serializers.PrimaryKeyRelatedField(
        queryset=MusicGenre.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="music_genres"
    )

    music_activity_ids = serializers.PrimaryKeyRelatedField(
        queryset=MusicActivity.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="music_activities"
    )

    reading_preference_ids = serializers.PrimaryKeyRelatedField(
        queryset=ReadingPreference.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="reading_preferences"
    )

    movie_tv_genre_ids = serializers.PrimaryKeyRelatedField(
        queryset=MovieGenre.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source="movie_tv_genres"
    )

    class Meta:
        model = PersonalLifestyle
        exclude = ("id", "profile")

    def update(self, instance, validated_data):
        m2m_fields = [
            "music_genres",
            "music_activities",
            "reading_preferences",
            "movie_tv_genres",
        ]

        for field in m2m_fields:
            if field in validated_data:
                getattr(instance, field).set(validated_data.pop(field))

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

    

class MatrimonyProfileSerializer(serializers.ModelSerializer):
    user = UserProfileSerializer()
    lifestyle = FetchPersonalLifestyleSerializer(required=False)
    
    # 🔹 Display religion and caste with both id and name
    religion = serializers.SerializerMethodField()
    caste = serializers.SerializerMethodField()
    
    # 🔹 Read-only user fields
    email = serializers.CharField(source="user.email", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    profile_reveal_count = serializers.IntegerField(source="user.profile_reveal_count", read_only=True)

    class Meta:
        model = MatrimonyProfile
        exclude = ("id", "created_at")

    def get_religion(self, obj):
        if obj.religion:
            return {
                "id": obj.religion.id,
                "name": obj.religion.name
            }
        return None

    def get_caste(self, obj):
        if obj.caste:
            return {
                "id": obj.caste.id,
                "name": obj.caste.name
            }
        return None

    def update(self, instance, validated_data):
        # ---- Update User ----
        user_data = validated_data.pop("user", None)
        if user_data:
            user_serializer = UserProfileSerializer(
                instance=instance.user,
                data=user_data,
                partial=True
            )
            user_serializer.is_valid(raise_exception=True)
            user_serializer.save()

        # ---- Update Matrimony Profile ----
        lifestyle_data = validated_data.pop("lifestyle", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # ---- Update / Create Lifestyle (Optional) ----
        if lifestyle_data:
            lifestyle, _ = PersonalLifestyle.objects.get_or_create(
                profile=instance
            )

            lifestyle_serializer = FetchPersonalLifestyleSerializer(
                instance=lifestyle,
                data=lifestyle_data,
                partial=True
            )
            lifestyle_serializer.is_valid(raise_exception=True)
            lifestyle_serializer.save()

        return instance
    

# user multiple images
class UserImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = UserImage
        fields = ("id", "image")

    def get_image(self, obj):
        request = self.context.get("request")
        if obj.image:
            return request.build_absolute_uri(obj.image.url) if request else obj.image.url
        return None

        
# blog serializer
class BlogListSerializer(serializers.ModelSerializer):
    cover_media_url = serializers.SerializerMethodField()
    cover_media_type = serializers.CharField(read_only=True)
    created_at_ist = serializers.SerializerMethodField()

    class Meta:
        model = Blog
        fields = [
            "id",
            "title",
            "short_description",
            "cover_media_url",
            "cover_media_type",
            "is_featured",
            "views_count",
            "created_at_ist",
        ]

    def get_cover_media_url(self, obj):
        request = self.context.get("request")
        if obj.cover_media and request:
            return request.build_absolute_uri(obj.cover_media.url)
        return None

    def get_created_at_ist(self, obj):
        ist = pytz.timezone("Asia/Kolkata")
        return obj.created_at.astimezone(ist).strftime("%d %b %Y, %I:%M %p")


class BlogDetailSerializer(serializers.ModelSerializer):
    cover_media_url = serializers.SerializerMethodField()
    cover_media_type = serializers.CharField(read_only=True)
    created_at_ist = serializers.SerializerMethodField()
    updated_at_ist = serializers.SerializerMethodField()

    class Meta:
        model = Blog
        fields = [
            "id",
            "title",
            "short_description",
            "content",
            "cover_media_url",
            "cover_media_type",
            "is_featured",
            "views_count",
            "created_at_ist",
            "updated_at_ist",
        ]

    def get_cover_media_url(self, obj):
        request = self.context.get("request")
        if obj.cover_media and request:
            return request.build_absolute_uri(obj.cover_media.url)
        return None

    def get_created_at_ist(self, obj):
        ist = pytz.timezone("Asia/Kolkata")
        return obj.created_at.astimezone(ist).strftime("%d %b %Y, %I:%M %p")

    def get_updated_at_ist(self, obj):
        ist = pytz.timezone("Asia/Kolkata")
        return obj.updated_at.astimezone(ist).strftime("%d %b %Y, %I:%M %p")



# fcm token serializer
class FCMTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["fcm_token"]

    def validate_fcm_token(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("FCM token cannot be empty")
        return value.strip()


class SendOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Request OTP for password reset via email or phone
    """
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=15, required=False, allow_blank=True)

    def validate(self, data):
        email = data.get("email")
        phone_number = data.get("phone_number")

        if not email and not phone_number:
            raise serializers.ValidationError(
                "Either email or phone_number is required"
            )

        if email:
            if not User.objects.filter(email=email, is_deleted=False).exists():
                raise serializers.ValidationError("Email not found")

        if phone_number:
            # Format phone number before lookup
            formatted_phone = format_phone_number(phone_number)
            if not formatted_phone:
                raise serializers.ValidationError("Invalid phone number format")
            
            if not User.objects.filter(phone_number=formatted_phone, is_deleted=False).exists():
                raise serializers.ValidationError("Phone number not found")
            
            # Update data with formatted phone number
            data["phone_number"] = formatted_phone

        return data


class ResetPasswordSerializer(serializers.Serializer):
    """
    Reset password with OTP verification
    """
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=15, required=False, allow_blank=True)
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, data):
        email = data.get("email")
        phone_number = data.get("phone_number")
        otp = data.get("otp")
        new_password = data.get("new_password")
        confirm_password = data.get("confirm_password")

        # Check if either email or phone is provided
        if not email and not phone_number:
            raise serializers.ValidationError(
                "Either email or phone_number is required"
            )

        # Check if passwords match
        if new_password != confirm_password:
            raise serializers.ValidationError("Passwords do not match")

        # Verify user exists
        user = None
        if email:
            try:
                user = User.objects.get(email=email, is_deleted=False)
            except User.DoesNotExist:
                raise serializers.ValidationError("Email not found")

        formatted_phone = None
        if phone_number:
            # Format phone number before lookup
            formatted_phone = format_phone_number(phone_number)
            if not formatted_phone:
                raise serializers.ValidationError("Invalid phone number format")
            
            try:
                user = User.objects.get(phone_number=formatted_phone, is_deleted=False)
            except User.DoesNotExist:
                raise serializers.ValidationError("Phone number not found")

        # Verify OTP if phone number is provided
        if formatted_phone:
            try:
                otp_obj = PhoneOTP.objects.get(
                    phone_number=formatted_phone,
                    is_verified=False  # Get unverified OTP (will verify during reset)
                )
            except PhoneOTP.DoesNotExist:
                raise serializers.ValidationError("Invalid OTP request")

            if otp_obj.is_expired():
                raise serializers.ValidationError("OTP has expired")

            if otp_obj.otp != otp:
                raise serializers.ValidationError("Invalid OTP")

        data["user"] = user
        return data


class DeleteAccountSerializer(serializers.Serializer):
    """
    Delete user account with OTP verification
    """
    phone_number = serializers.CharField(max_length=15, required=True)
    otp = serializers.CharField(max_length=6, required=True)

    def validate(self, data):
        phone_number = data.get("phone_number")
        otp = data.get("otp")

        if not phone_number or not otp:
            raise serializers.ValidationError(
                "Phone number and OTP are required"
            )

        # Format phone number before lookup
        formatted_phone = format_phone_number(phone_number)
        if not formatted_phone:
            raise serializers.ValidationError("Invalid phone number format")

        # Verify user exists
        try:
            user = User.objects.get(phone_number=formatted_phone, is_deleted=False)
        except User.DoesNotExist:
            raise serializers.ValidationError("Phone number not found")

        # Verify OTP — must be already verified via verify-otp endpoint
        try:
            otp_obj = PhoneOTP.objects.get(
                phone_number=formatted_phone,
                otp=otp,
                is_verified=True  # Must have been verified via verify-otp first
            )
        except PhoneOTP.DoesNotExist:
            raise serializers.ValidationError("Invalid or unverified OTP. Please verify your OTP first.")

        if otp_obj.is_expired():
            raise serializers.ValidationError("OTP has expired")

        data["user"] = user
        data["formatted_phone"] = formatted_phone
        return data