from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from .models import SubscriptionPayment, CustomUser


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 10})
def expire_subscriptions(self):
    now = timezone.now()

    expired_payments = SubscriptionPayment.objects.filter(
        payment_status="success",
        expires_at__isnull=False,
        expires_at__lt=now,
        user__is_premium=True
    ).select_related("user")

    expired_users = set()

    for payment in expired_payments:
        payment.payment_status = "refunded"  # or "expired" (better – see note)
        payment.save(update_fields=["payment_status"])

        expired_users.add(payment.user)

    # Update users in bulk
    for user in expired_users:
        user.is_premium = False
        user.save(update_fields=["is_premium"])

    return f"Expired {len(expired_users)} subscriptions"


@shared_task(bind=True)
def hard_delete_soft_deleted_users(self):
    """
    Hard delete users who were soft deleted 30 days ago
    """
    print("\n" + "🔥 " + "=" * 60)
    print("🔥 HARD DELETE SOFT DELETED USERS TASK STARTED")
    print("🔥 " + "=" * 60)
    
    now = timezone.now()
    delete_threshold = now - timedelta(days=30)
    
    # Find soft deleted users older than 30 days
    soft_deleted_users = CustomUser.objects.filter(
        is_deleted=True,
        deleted_at__lte=delete_threshold
    )
    
    user_count = soft_deleted_users.count()
    print(f"📊 Found {user_count} users to hard delete")
    
    if user_count == 0:
        print("✅ No users to delete")
        print("=" * 70 + "\n")
        return "No users to delete"
    
    # Import match app models for cascading deletes
    from match.models import MatchRequest, Notification, SuccessStory, ContactInfoView
    
    deleted_count = 0
    error_count = 0
    
    for user in soft_deleted_users:
        try:
            print(f"\n🗑️ Processing user: {user.email}")
            
            # Delete notifications
            Notification.objects.filter(recipient=user).delete()
            Notification.objects.filter(sender=user).delete()
            print(f"  ✓ Notifications deleted")
            
            # Delete match requests
            MatchRequest.objects.filter(from_user=user).delete()
            MatchRequest.objects.filter(to_user=user).delete()
            print(f"  ✓ Match requests deleted")
            
            # Delete contact info views
            ContactInfoView.objects.filter(viewer=user).delete()
            ContactInfoView.objects.filter(viewed_user=user).delete()
            print(f"  ✓ Contact info views deleted")
            
            # Delete success stories
            success_stories = SuccessStory.objects.filter(created_by=user)
            for story in success_stories:
                story.images.all().delete()
            success_stories.delete()
            print(f"  ✓ Success stories deleted")
            
            # Delete user data
            from auth_api.models import UserImage, PersonalLifestyle, MatrimonyProfile, SubscriptionPayment, PhoneOTP
            
            UserImage.objects.filter(user=user).delete()
            PersonalLifestyle.objects.filter(profile__user=user).delete()
            MatrimonyProfile.objects.filter(user=user).delete()
            SubscriptionPayment.objects.filter(user=user).delete()
            PhoneOTP.objects.filter(phone_number=user.phone_number).delete()
            print(f"  ✓ User data deleted")
            
            # Hard delete user
            user.delete()
            print(f"  ✓ User account permanently deleted")
            
            deleted_count += 1
            
        except Exception as e:
            error_count += 1
            print(f"  ❌ Error deleting user: {str(e)}")
    
    print("\n" + "=" * 60)
    print(f"✅ Hard delete task completed")
    print(f"📊 Successfully deleted: {deleted_count} users")
    print(f"⚠️  Errors: {error_count} users")
    print("=" * 70 + "\n")
    
    return f"Hard deleted {deleted_count} users, {error_count} errors"


