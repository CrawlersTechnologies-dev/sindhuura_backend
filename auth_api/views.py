from rest_framework.views import APIView
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import *
from .api_response import APIResponseMixin
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework import status as drf_status
from django.contrib.auth import authenticate
import razorpay
import re
from decimal import Decimal
from datetime import timedelta
from rest_framework.response import Response
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.shortcuts import get_object_or_404
from backend.models import Blog
from django.db.models import F
from django.db import transaction
from django.db.models import Q
from django.db import models
from .pagination import BlogPagination
from .utils import send_sms_otp,send_registration_sms
import random
# register API View
class RegisterAPIView(APIResponseMixin, APIView):

    permission_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if not serializer.is_valid():
            return self.error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )

        user, profile = serializer.save()

        # 🔐 Generate JWT Tokens
        refresh = RefreshToken.for_user(user)

        # ✅ Send Registration SMS (NON-BLOCKING recommended)
        try:
            sms_sent = send_registration_sms(phone_number=user.phone_number)
            print(f"[REGISTER] SMS result for {user.phone_number}: {sms_sent}")
        except Exception as e:
            print(f"[REGISTER] SMS exception: {e}")

        response_data = {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "unique_id": user.unique_id,
            },
            "profile": {
                "id": profile.id
            }
        }

        return self.success_response(
            message="Registration successful",
            data=response_data,
            status_code=status.HTTP_201_CREATED
        )
    
# Personal details API
class PersonalLifestyleAPIView(APIResponseMixin, APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Create or Update Personal Lifestyle
        """

        try:
            profile = request.user.profile
        except:
            return self.error_response(
                "Matrimony profile not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        serializer = PersonalLifestyleSerializer(
            data=request.data,
            context={"profile": profile}
        )

        if not serializer.is_valid():
            return self.error_response(
                serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )

        lifestyle = serializer.save()

        return self.success_response(
            message="Personal lifestyle details saved successfully",
            data={
                "lifestyle_id": lifestyle.id
            },
            status_code=status.HTTP_201_CREATED
        )
    
class LifestyleMasterDataAPIView(APIView, APIResponseMixin):
    permission_classes = [IsAuthenticated]   # Public API (used during registration)

    def get(self, request):
        try:
            data = {
                "user_id": request.user.unique_id,
                "music_genres": MusicGenreSerializer(
                    MusicGenre.objects.all(), many=True
                ).data,
            
                "music_activities": MusicActivitySerializer(
                    MusicActivity.objects.all(), many=True
                ).data,
            
                "reading_preferences": ReadingPreferenceSerializer(
                    ReadingPreference.objects.all(), many=True
                ).data,
            
                "movie_tv_genres": MovieGenreSerializer(
                    MovieGenre.objects.all(), many=True
                ).data,
            }


            return self.success_response(
                message="Lifestyle master data fetched successfully",
                data=data
            )

        except Exception as e:
            return self.error_response(str(e))
        
# subscription plans API
class SubscriptionPlanListAPI(APIView, APIResponseMixin):

    def get(self, request):
        try:
            plans = SubscriptionPlan.objects.filter(is_active=True)

            serializer = SubscriptionPlanSerializer(plans, many=True)

            return self.success_response(
                message="Subscription plans fetched successfully",
                data=serializer.data,
                status_code=drf_status.HTTP_200_OK
            )

        except Exception as e:
            return self.error_response(
                errors=str(e),
                status_code=drf_status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

class UserMultipleImageUploadAPI(APIResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MultipleImageUploadSerializer(
            data=request.data
        )

        if not serializer.is_valid():
            return self.error_response(serializer.errors)

        images = serializer.validated_data["images"]

        try:
            with transaction.atomic():
                image_objs = [
                    UserImage(user=request.user, image=image)
                    for image in images
                ]
                UserImage.objects.bulk_create(image_objs)

            return self.success_response(
                message="Images uploaded successfully",
                data={
                    "uploaded_count": len(images)
                }
            )

        except Exception as e:
            return self.error_response(str(e))
        

class ReligionListAPIView(APIResponseMixin, APIView):

    permission_classes = [AllowAny]

    def get(self, request):
        religions = Caste.objects.filter(
            level="religion",
            is_active=True
        ).order_by("name")

        serializer = ReligionSerializer(religions, many=True)

        return self.success_response(
            message="Religions fetched successfully",
            data=serializer.data
        )
    

class CasteListByReligionAPIView(APIResponseMixin, APIView):

    permission_classes = [AllowAny]

    def get(self, request):
        religion_id = request.query_params.get("religion_id")

        if not religion_id:
            return self.error_response(
                errors="religion_id is required"
            )

        castes = Caste.objects.filter(
            level="caste",
            parent_id=religion_id,
            is_active=True
        ).order_by("name")

        serializer = CasteSerializer(castes, many=True)

        return self.success_response(
            message="Castes fetched successfully",
            data=serializer.data
        )


# login API
class LoginAPIView(APIResponseMixin, APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if not serializer.is_valid():
            return self.error_response(serializer.errors)

        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        user = authenticate(request, email=email, password=password)

        if not user:
            # Check if email belongs to a soft-deleted user (and no active user exists)
            if not CustomUser.objects.filter(email=email, is_deleted=False).exists():
                deleted_user = CustomUser.objects.filter(
                    is_deleted=True,
                    email__istartswith=email
                ).first()
                if deleted_user:
                    parts = deleted_user.email.split('_deleted_')
                    if len(parts) == 2 and parts[0].lower() == email.lower():
                        return self.error_response(
                            errors="This account has been deleted. You can reactivate within 30 days by contacting support.",
                            status_code=drf_status.HTTP_403_FORBIDDEN
                        )

            return self.error_response(
                errors="Invalid email or password",
                status_code=drf_status.HTTP_401_UNAUTHORIZED
            )
        
        # Check if account is soft deleted
        if user.is_deleted:
            return self.error_response(
                errors="This account has been deleted. You can reactivate within 30 days by contacting support.",
                status_code=drf_status.HTTP_403_FORBIDDEN
            )

        if not user.is_active:
            return self.error_response(
                errors="Account is disabled. Please contact support.",
                status_code=drf_status.HTTP_403_FORBIDDEN
            )

        # 🔐 Generate JWT Tokens
        refresh = RefreshToken.for_user(user)

        data = {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "phone_number": user.phone_number,
                "role": user.role,
                "is_email_verified": user.is_email_verified,
                "profile_image": (
                    request.build_absolute_uri(user.profile_image.url)
                    if user.profile_image else None
                )
            }
        }

        return self.success_response(
            message="Login successful",
            data=data,
            status_code=drf_status.HTTP_200_OK
        )
    
class CreateSubscriptionOrderAPIView(APIView, APIResponseMixin):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        print("🔥 API HIT 🔥")
        print("RAZORPAY KEY:", settings.RAZORPAY_KEY_ID)

        subscription_id = request.data.get("subscription_id")

        if not subscription_id:
            return self.error_response("subscription_id is required")

        try:
            plan = SubscriptionPlan.objects.get(
                id=subscription_id,
                is_active=True
            )
        except SubscriptionPlan.DoesNotExist:
            return self.error_response("Invalid subscription plan")

        # ✅ Check if user already has an active subscription
        if request.user.is_subscribed and request.user.subscription_expires_at:
            if request.user.subscription_expires_at > timezone.now():
                return self.error_response(
                    errors="You already have an active subscription plan. Please wait for it to expire or contact support.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        amount_paise = int(float(plan.price) * 100)
        if amount_paise <= 0:
            return self.error_response("Invalid amount")

        try:
            client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )

            razorpay_order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"sub_{plan.id}_{request.user.id}",
            })

        except razorpay.errors.BadRequestError as e:
            return self.error_response(str(e))

        payment = SubscriptionPayment.objects.create(
            user=request.user,
            subscription=plan,
            amount=plan.price,
            payment_method="razorpay",
            transaction_id=razorpay_order["id"],
            payment_status="pending"
        )

        return self.success_response(
            message="Order created successfully",
            data={
                "payment_id": payment.id,
                "razorpay_order_id": razorpay_order["id"],
                "razorpay_key": settings.RAZORPAY_KEY_ID,
                "amount": amount_paise,
                "currency": "INR",
                "plan_name": plan.plan_name
            }
        )
    
class VerifySubscriptionPaymentAPIView(APIView, APIResponseMixin):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        razorpay_order_id = request.data.get("razorpay_order_id")
        razorpay_payment_id = request.data.get("razorpay_payment_id")
        razorpay_signature = request.data.get("razorpay_signature")

        try:
            payment = SubscriptionPayment.objects.select_related("subscription").get(
                transaction_id=razorpay_order_id,
                user=request.user
            )
        except SubscriptionPayment.DoesNotExist:
            return self.error_response("Payment record not found")

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

        # ✅ Verify Razorpay signature
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            payment.payment_status = "failed"
            payment.save(update_fields=["payment_status"])
            return self.error_response("Payment verification failed")

        # ✅ Mark payment success
        payment.payment_status = "success"
        payment.paid_at = timezone.now()
        payment.expires_at = payment.paid_at + timedelta(
            days=payment.subscription.validity
        )
        payment.save(update_fields=["payment_status", "paid_at", "expires_at"])

        # ✅ ACTIVATE SUBSCRIPTION
        user = payment.user
        expiry = payment.expires_at

        user.is_subscribed = True
        user.subscription_expires_at = expiry
        user.profile_reveal_count = 0  # Reset reveal count for new plan
        user.save(update_fields=[
            "is_subscribed",
            "subscription_expires_at",
            "profile_reveal_count"
        ])

        return self.success_response(
            message="Payment verified and subscription activated successfully",
            data={
                "payment_id": payment.id,
                "status": payment.payment_status,
                "plan": payment.subscription.plan_name,
                "expires_at": expiry,
                "reveal_limit": payment.subscription.reveal_limit
            }
        )
# user profile API
class MatrimonyProfileAPIView(APIView, APIResponseMixin):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = MatrimonyProfile.objects.filter(user=request.user).first()

        if not profile:
            return self.error_response(
                "Profile not found",
                status.HTTP_404_NOT_FOUND
            )

        serializer = MatrimonyProfileSerializer(
            profile,
            context={"request": request}
        )

        data = serializer.data

        # 🔹 Subscription Details
        subscription_plan = None
        reveal_limit = 0
        reveal_contact_count = 0
        reveal_remaining = 0
        expiry_date = None

        # Get latest successful payment
        latest_payment = SubscriptionPayment.objects.filter(
            user=request.user,
            payment_status='success'
        ).order_by('-paid_at').first()

        if latest_payment and latest_payment.paid_at:
            expiry_date = latest_payment.paid_at + timedelta(
                days=latest_payment.subscription.validity
            )

            # Check if subscription is active
            if expiry_date >= timezone.now():
                subscription_plan = latest_payment.subscription.plan_name
                reveal_limit = latest_payment.subscription.reveal_limit
                reveal_contact_count = request.user.profile_reveal_count
                reveal_remaining = max(
                    0,
                    reveal_limit - reveal_contact_count
                )

        data['subscription'] = {
            'plan': subscription_plan or 'none',
            'reveal_limit': reveal_limit,
            'reveal_contact_count': reveal_contact_count,
            'reveal_remaining': reveal_remaining,
            'expiry_date': expiry_date.isoformat() if expiry_date else None
        }

        return self.success_response(
            message="Profile fetched successfully",
            data=data
        )

    def patch(self, request):
        profile = MatrimonyProfile.objects.filter(user=request.user).first()

        if not profile:
            return self.error_response(
                "Profile not found. Create profile first.",
                status.HTTP_404_NOT_FOUND
            )

        serializer = MatrimonyProfileSerializer(
            instance=profile,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        if serializer.is_valid():
            serializer.save()
            return self.success_response(
                message="Profile updated successfully",
                data=serializer.data
            )

        return self.error_response(serializer.errors)


class UserImageListAPIView(APIResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            images = UserImage.objects.filter(
                user=request.user
            ).order_by("-uploaded_at")

            serializer = UserImageSerializer(
                images,
                many=True,
                context={"request": request}
            )

            return self.success_response(
                message="User images fetched successfully",
                data=serializer.data,
                status_code=status.HTTP_200_OK
            )

        except Exception as e:
            return self.error_response(
                errors=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
# remove image
class UserImageDeleteAPIView(APIResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, image_id):
        try:
            image = get_object_or_404(
                UserImage,
                id=image_id,
                user=request.user  # 🔐 ownership check
            )

            image.delete()

            return self.success_response(
                message="Image deleted successfully",
                data=[],
                status_code=status.HTTP_200_OK
            )

        except Exception as e:
            return self.error_response(
                errors=str(e),
                status_code=status.HTTP_400_BAD_REQUEST
            )


# blog list API
class BlogListAPIView(APIView, APIResponseMixin):
    permission_classes = [AllowAny]

    def get(self, request):
        blogs = Blog.objects.filter(status="published")

        # Featured filter
        if request.GET.get("featured") == "true":
            blogs = blogs.filter(is_featured=True)

        # 🔍 Search filter
        search = request.GET.get("search")
        if search:
            blogs = blogs.filter(
                Q(title__icontains=search) |
                Q(short_description__icontains=search) |
                Q(content__icontains=search)
            )

        paginator = BlogPagination()
        paginated_blogs = paginator.paginate_queryset(blogs, request)

        serializer = BlogListSerializer(
            paginated_blogs,
            many=True,
            context={"request": request}
        )

        return self.success_response(
            message="Blogs fetched successfully",
            data={
                "count": blogs.count(),
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "results": serializer.data
            }
        )

    
class BlogDetailAPIView(APIView, APIResponseMixin):
    permission_classes = [AllowAny]

    def get(self, request, blog_id):
        try:
            blog = Blog.objects.get(id=blog_id, status="published")
        except Blog.DoesNotExist:
            return self.error_response(
                "Blog not found",
                status_code=drf_status.HTTP_404_NOT_FOUND
            )

        # 🔥 Increment views count safely
        Blog.objects.filter(id=blog.id).update(
            views_count=F("views_count") + 1
        )
        blog.refresh_from_db()

        serializer = BlogDetailSerializer(
            blog,
            context={"request": request}
        )

        return self.success_response(
            message="Blog fetched successfully",
            data=serializer.data
        )
    

# update fcm token API
class UpdateFCMTokenAPIView(APIView, APIResponseMixin):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FCMTokenSerializer(
            instance=request.user,
            data=request.data,
            partial=True
        )

        if not serializer.is_valid():
            return self.error_response(serializer.errors)

        serializer.save()

        return self.success_response(
            message="FCM token updated successfully",
            data={
                "fcm_token": serializer.data["fcm_token"]
            },
            status_code=drf_status.HTTP_200_OK
        )
    

import re
# views.py
import random
import re
from django.core.cache import cache

def validate_and_format_phone(phone_number):
    """
    Validate and format Indian phone number to +91XXXXXXXXXX format
    """
    print(f"\n[INFO] Validating phone: '{phone_number}'")
    
    # Remove any spaces and dashes
    phone = re.sub(r'[\s\-]', '', str(phone_number))
    print(f"[INFO] After cleanup: '{phone}'")
    
    # If it starts with +91 and is correct length
    if phone.startswith('+91') and len(phone) == 13:
        print(f"[SUCCESS] Valid format (with +91): {phone}")
        return phone
    
    # If it starts with 91 (without +)
    if phone.startswith('91') and len(phone) == 12:
        result = f"+{phone}"
        print(f"[SUCCESS] Valid format (91 prefix, adding +): {result}")
        return result
    
    # If it's 10 digits, add +91
    if len(phone) == 10 and phone[0] in '6789':
        result = f"+91{phone}"
        print(f"[SUCCESS] Valid format (10 digits, adding +91): {result}")
        return result
    
    print(f"[ERROR] Invalid format")
    return None


class SendOTPAPIView(APIView, APIResponseMixin):
    def post(self, request):
        print("\n" + "🎬 " + "=" * 60)
        print("🎬 SEND OTP API CALLED")
        print("🎬 " + "=" * 60)
        
        phone_number = request.data.get("phone_number", "").strip()
        print(f"📥 Received phone_number: '{phone_number}'")

        if not phone_number:
            print("❌ Phone number is empty")
            return self.error_response("Phone number is required")
        
        # Validate and format phone number
        formatted_phone = validate_and_format_phone(phone_number)
        
        if not formatted_phone:
            print("❌ Phone validation failed")
            return self.error_response("Invalid phone number format. Use 10-digit Indian mobile number")
        
        print(f"✅ Formatted phone: {formatted_phone}")
        
        # Rate limiting
        cache_key = f"otp_limit_{formatted_phone}"
        print(f"\n🔒 Checking rate limit with key: {cache_key}")
        
        if cache.get(cache_key):
            print("⏳ Rate limit hit - user must wait")
            return self.error_response("Please wait 1 minute before requesting another OTP")
        
        print("✅ Rate limit check passed")

        # Generate OTP
        otp = str(random.randint(100000, 999999))
        print(f"\n🎲 Generated OTP: {otp}")
        
        # Delete old unverified OTPs
        deleted_count = PhoneOTP.objects.filter(
            phone_number=formatted_phone,
            is_verified=False
        ).delete()[0]
        print(f"🗑️ Deleted {deleted_count} old unverified OTPs")

        # Create new OTP
        print(f"💾 Creating new OTP record in database...")
        otp_obj = PhoneOTP.objects.create(
            phone_number=formatted_phone,
            otp=otp
        )
        print(f"✅ OTP record created: ID={otp_obj.id}")

        # Send SMS
        print(f"\n📤 Attempting to send SMS...")
        sms_result = send_sms_otp(formatted_phone, otp)
        print(f"\n📬 SMS Send Result: {sms_result}")
        
        if not sms_result:
            print("❌ SMS sending failed")
            return self.error_response(
                "Failed to send OTP",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        print("✅ SMS sent successfully")
        
        # Set rate limit
        cache.set(cache_key, True, 60)
        print(f"🔒 Rate limit set for 60 seconds")

        print("🎉 OTP process completed successfully")
        print("=" * 70 + "\n")
        
        return self.success_response(message="OTP sent successfully")

class VerifyOTPAPIView(APIView, APIResponseMixin):
    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        otp = request.data.get("otp", "").strip()

        if not phone_number or not otp:
            return self.error_response("Phone number and OTP are required")

        # Validate and format phone number
        formatted_phone = validate_and_format_phone(phone_number)
        
        if not formatted_phone:
            return self.error_response("Invalid phone number format")

        try:
            otp_obj = PhoneOTP.objects.get(
                phone_number=formatted_phone,
                is_verified=False
            )
        except PhoneOTP.DoesNotExist:
            return self.error_response("Invalid OTP")

        if otp_obj.is_expired():
            return self.error_response("OTP expired")
        
        # Compare OTP as plain text (not hashed)
        if otp_obj.otp != otp:
            return self.error_response("Invalid OTP")

        otp_obj.is_verified = True
        otp_obj.save()

        return self.success_response(message="OTP verified successfully")


class ResendOTPAPIView(APIView, APIResponseMixin):
    """
    Resend OTP to a phone number that already has a pending OTP request.
    Applies rate limiting to prevent abuse.
    """
    def post(self, request):
        print("\n" + "🔄 " + "=" * 60)
        print("🔄 RESEND OTP API CALLED")
        print("🔄 " + "=" * 60)
        
        phone_number = request.data.get("phone_number", "").strip()
        print(f"📥 Received phone_number: '{phone_number}'")

        if not phone_number:
            print("❌ Phone number is empty")
            return self.error_response("Phone number is required")
        
        # Validate and format phone number
        formatted_phone = validate_and_format_phone(phone_number)
        
        if not formatted_phone:
            print("❌ Phone validation failed")
            return self.error_response("Invalid phone number format. Use 10-digit Indian mobile number")
        
        print(f"✅ Formatted phone: {formatted_phone}")
        
        # Check if OTP exists for this phone (either verified or not)
        try:
            existing_otp = PhoneOTP.objects.filter(
                phone_number=formatted_phone
            ).latest('created_at')
            print(f"✅ Found existing OTP record for resend")
        except PhoneOTP.DoesNotExist:
            print("❌ No OTP request found for this phone number")
            return self.error_response(
                "No OTP request found. Please request a new OTP first.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        # Rate limiting for resend
        cache_key = f"otp_resend_limit_{formatted_phone}"
        print(f"\n🔒 Checking resend rate limit with key: {cache_key}")
        
        if cache.get(cache_key):
            print("⏳ Resend rate limit hit - user must wait")
            return self.error_response(
                "Please wait 1 minute before requesting another OTP",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        print("✅ Resend rate limit check passed")

        # Generate new OTP
        otp = str(random.randint(100000, 999999))
        print(f"\n🎲 Generated new OTP: {otp}")
        
        # Delete old OTPs
        deleted_count = PhoneOTP.objects.filter(
            phone_number=formatted_phone
        ).delete()[0]
        print(f"🗑️ Deleted {deleted_count} old OTP records")

        # Create new OTP
        print(f"💾 Creating new OTP record in database...")
        otp_obj = PhoneOTP.objects.create(
            phone_number=formatted_phone,
            otp=otp
        )
        print(f"✅ OTP record created: ID={otp_obj.id}")

        # Send SMS
        print(f"\n📤 Attempting to send SMS...")
        sms_result = send_sms_otp(formatted_phone, otp)
        print(f"\n📬 SMS Send Result: {sms_result}")
        
        if not sms_result:
            print("❌ SMS sending failed")
            return self.error_response(
                "Failed to resend OTP",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        print("✅ SMS sent successfully")
        
        # Set resend rate limit
        cache.set(cache_key, True, 60)
        print(f"🔒 Resend rate limit set for 60 seconds")

        print("🎉 OTP resend process completed successfully")
        print("=" * 70 + "\n")
        
        return self.success_response(message="OTP resent successfully")


class ForgotPasswordAPIView(APIView, APIResponseMixin):
    """
    Request OTP for password reset via phone number
    """
    def post(self, request):
        print("\n" + "🔐 " + "=" * 60)
        print("🔐 FORGOT PASSWORD API CALLED")
        print("🔐 " + "=" * 60)
        
        serializer = ForgotPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            return self.error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )

        phone_number = serializer.validated_data.get("phone_number")
        email = serializer.validated_data.get("email")

        # Get user by email or phone
        user = None
        contact_identifier = None
        
        if email:
            user = User.objects.filter(email=email).first()
            contact_identifier = email
            print(f"📧 Searching user by email: {email}")
        elif phone_number:
            formatted_phone = validate_and_format_phone(phone_number)
            user = User.objects.filter(phone_number=formatted_phone).first()
            contact_identifier = formatted_phone
            print(f"📱 Searching user by phone: {formatted_phone}")

        if not user:
            print("❌ User not found")
            return self.error_response(
                "User not found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        print(f"✅ User found: {user.email}")

        # Generate OTP only for phone-based password reset
        if phone_number:
            formatted_phone = validate_and_format_phone(phone_number)
            
            # Rate limiting
            cache_key = f"forgot_pwd_limit_{formatted_phone}"
            if cache.get(cache_key):
                print("⏳ Rate limit hit - user must wait")
                return self.error_response(
                    "Please wait 1 minute before requesting another OTP",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # Generate OTP
            otp = str(random.randint(100000, 999999))
            print(f"🎲 Generated OTP: {otp}")

            # Delete old OTPs
            deleted_count = PhoneOTP.objects.filter(
                phone_number=formatted_phone,
                is_verified=False
            ).delete()[0]
            print(f"🗑️ Deleted {deleted_count} old OTPs")

            # Create new OTP
            otp_obj = PhoneOTP.objects.create(
                phone_number=formatted_phone,
                otp=otp
            )
            print(f"✅ OTP created: {otp_obj.id}")

            # Send SMS
            print(f"📤 Sending OTP via SMS...")
            sms_result = send_sms_otp(formatted_phone, otp)
            
            if not sms_result:
                print("❌ SMS sending failed")
                return self.error_response(
                    "Failed to send OTP",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Set rate limit
            cache.set(cache_key, True, 60)
            print(f"✅ SMS sent successfully, rate limit set")

            print("🎉 Forgot password process completed successfully")
            print("=" * 70 + "\n")
            
            return self.success_response(
                message="OTP sent to your phone. Please verify to reset password.",
                data={"contact": formatted_phone}
            )

        return self.error_response(
            "Phone number is required for password reset",
            status_code=status.HTTP_400_BAD_REQUEST
        )


class ResetPasswordAPIView(APIView, APIResponseMixin):
    """
    Reset password with OTP verification
    """
    def post(self, request):
        print("\n" + "🔑 " + "=" * 60)
        print("🔑 RESET PASSWORD API CALLED")
        print("🔑 " + "=" * 60)
        
        serializer = ResetPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            return self.error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )

        user = serializer.validated_data.get("user")
        phone_number = serializer.validated_data.get("phone_number")
        new_password = serializer.validated_data.get("new_password")
        otp = serializer.validated_data.get("otp")

        print(f"👤 Resetting password for user: {user.email}")
        print(f"🔏 Verifying OTP: {otp}")

        # Format phone if provided
        if phone_number:
            formatted_phone = validate_and_format_phone(phone_number)
            print(f"📱 Phone: {formatted_phone}")

            # Verify OTP (already validated in serializer, but get it for cleanup)
            try:
                otp_obj = PhoneOTP.objects.get(
                    phone_number=formatted_phone,
                    otp=otp
                )
                print("✅ OTP record found")
            except PhoneOTP.DoesNotExist:
                print("❌ OTP not found")
                return self.error_response(
                    "OTP not found",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        # Update password
        print(f"🔄 Updating password...")
        user.set_password(new_password)
        user.save()
        print(f"✅ Password updated successfully")

        # Mark OTP as verified and clean up after successful reset
        if phone_number:
            formatted_phone = validate_and_format_phone(phone_number)
            PhoneOTP.objects.filter(
                phone_number=formatted_phone,
                otp=otp
            ).update(is_verified=True)
            print(f"✅ OTP marked as verified")

        print("🎉 Password reset completed successfully")
        print("=" * 70 + "\n")

        return self.success_response(
            message="Password reset successfully. You can now login with your new password.",
            status_code=status.HTTP_200_OK
        )


class DeleteAccountAPIView(APIView, APIResponseMixin):
    """
    Delete user account with OTP verification
    """
    permission_classes = [AllowAny]

    def post(self, request):
        print("\n" + "🗑️ " + "=" * 60)
        print("🗑️ DELETE ACCOUNT API CALLED")
        print("🗑️ " + "=" * 60)
        
        serializer = DeleteAccountSerializer(data=request.data)
        
        if not serializer.is_valid():
            return self.error_response(
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )

        user = serializer.validated_data.get("user")
        phone_number = serializer.validated_data.get("formatted_phone")
        otp = request.data.get("otp")

        print(f"👤 Deleting account for user: {user.email}")
        print(f"📱 Phone: {phone_number}")
        print(f"🔏 OTP verified: {otp}")

        try:
            with transaction.atomic():
                # Soft delete: Mark user as deleted instead of hard delete
                user.is_deleted = True
                user.deleted_at = timezone.now()
                user.is_active = False  # Deactivate account immediately
                
                # Suffix email to release unique constraint for fresh registration
                suffix = f"_deleted_{int(timezone.now().timestamp())}"
                user.email = f"{user.email[:200]}{suffix}"
                
                user.save()
                
                print(f"🗑️ Soft deleted user account: {user.email}")
                print(f"⏰ Scheduled for hard deletion on: {user.deleted_at + timezone.timedelta(days=30)}")

        except Exception as e:
            print(f"❌ Error soft deleting account: {str(e)}")
            return self.error_response(
                f"Error deleting account: {str(e)}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        print("🎉 Account soft deleted successfully")
        print("=" * 70 + "\n")

        return self.success_response(
            message="Your account has been marked for deletion. It will be permanently deleted after 30 days.",
            status_code=status.HTTP_200_OK
        )


class CheckEmailExistsAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        phone_number = request.data.get("phone_number")

        if not email and not phone_number:
            return Response(
                {
                    "status": False,
                    "message": "Email or Phone number is required",
                    "response": []
                },
                status=400
            )

        email_exists = False
        phone_exists = False

        if email:
            email_exists = User.objects.filter(email__iexact=email, is_deleted=False).exists()

        if phone_number:
            formatted_phone = validate_and_format_phone(phone_number) or phone_number
            phone_exists = User.objects.filter(phone_number=formatted_phone, is_deleted=False).exists()

        return Response(
            {
                "status": True,
                "message": "Check completed",
                "response": {
                    "email": email,
                    "email_exists": email_exists,
                    "phone_number": phone_number,
                    "phone_exists": phone_exists
                }
            },
            status=200
        )