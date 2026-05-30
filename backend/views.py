from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login,logout
from django.contrib import messages
from auth_api.models import CustomUser as User, SubscriptionPayment
from match.models import StoryBanner, MatchRequest, SuccessStory
from .models import *
from django.shortcuts import get_object_or_404
from auth_api.models import CustomUser
from django.contrib.auth.hashers import make_password
from django.db.models import Exists, OuterRef, Count, Sum
from django.core.mail import EmailMessage
from django.conf import settings
from match.models import SuccessStory
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt  # Only if you don't use csrf token in JS
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
import json
from django.shortcuts import render, redirect
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import render
from django.db.models import Q
from match.models import MatchRequest
from django.db.models import Sum
from django.utils.timezone import make_aware
from datetime import datetime, timedelta
import pytz

def index(request):
    return render(request,'index.html')

def admin_login(request):
    # Already logged-in admin / sub-admin
    if request.user.is_authenticated and request.user.is_staff:
        if request.user.role == "admin":
            return redirect("admin_dashboard")
        elif request.user.role == "sub_admin":
            return redirect("sub_admin_dashboard")

    if request.method == "POST":
        email_username = request.POST.get("email_username")
        password = request.POST.get("password")
        remember_me = request.POST.get("remember_me")
        
        try:
            user = CustomUser.objects.get(email=email_username)
        except CustomUser.DoesNotExist:
            messages.error(request, "No account found with this email.")
            return render(request, "admin_login.html")
        
        # Manually check password
        if user.check_password(password):
            if not user.is_active:
                messages.error(request, "Your account is inactive. Please contact admin.")
            elif not user.is_staff:
                messages.error(request, "You are not authorized to access the admin panel.")
            else:
                login(request, user)
                if remember_me:
                    request.session.set_expiry(60 * 60 * 24 * 14)  # 14 days
                else:
                    request.session.set_expiry(0)  # browser close
                
                if user.role == "admin":
                    return redirect("admin_dashboard")
                elif user.role == "sub_admin":
                    return redirect("sub_admin_dashboard")
                else:
                    messages.error(request, "Invalid role access.")
                    logout(request)
        else:
            messages.error(request, "Invalid password.")
        
        return render(request, "admin_login.html")

    return render(request, "admin_login.html")

def admin_dashboard(request):
    # if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
    #     return redirect('admin_login')

    # Statistics
    total_users = CustomUser.objects.filter(is_staff=False, is_deleted=False).count()
    verified_users = CustomUser.objects.filter(is_staff=False, is_verified=True, is_deleted=False).count()
    premium_users = SubscriptionPayment.objects.filter(payment_status='success').values('user').distinct().count()
    total_matches = MatchRequest.objects.count()
    accepted_matches = MatchRequest.objects.filter(status='accepted').count()
    success_stories = SuccessStory.objects.count()
    blogs = Blog.objects.count()
    events = Event.objects.count()
    total_revenue = SubscriptionPayment.objects.filter(payment_status='success').aggregate(total=Sum('amount'))['total'] or 0

    # Recent activities (last 10)
    recent_users = CustomUser.objects.filter(is_staff=False, is_deleted=False).order_by('-date_joined')[:5]
    recent_matches = MatchRequest.objects.select_related('from_user', 'to_user').order_by('-created_at')[:5]
    recent_payments = SubscriptionPayment.objects.select_related('user').filter(payment_status='success').order_by('-paid_at')[:5]

    context = {
        'total_users': total_users,
        'verified_users': verified_users,
        'premium_users': premium_users,
        'total_matches': total_matches,
        'accepted_matches': accepted_matches,
        'success_stories': success_stories,
        'blogs': blogs,
        'events': events,
        'total_revenue': total_revenue,
        'recent_users': recent_users,
        'recent_matches': recent_matches,
        'recent_payments': recent_payments,
    }

    return render(request, 'admin_dashboard.html', context)

def sub_admin_dashboard(request):
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return redirect('admin_login')
    return render(request, 'sub_admin_dashboard.html')

def logout_view(request):
    logout(request)
    return redirect('admin_login')

def castes(request):
    if request.method == "POST":
        name = request.POST.get("name")
        parent_id = request.POST.get("parent")

        parent = Caste.objects.get(id=parent_id) if parent_id else None
        level = 'caste' if parent else 'religion'

        Caste.objects.create(
            name=name,
            parent=parent,
            level=level
        )

        messages.success(request, "Saved successfully")
        return redirect('castes')

    religions = Caste.objects.filter(level='religion')

    return render(request, 'castes.html', {
        'religions': religions
    })


def edit_caste(request, pk):
    caste = get_object_or_404(Caste, pk=pk)

    if request.method == "POST":
        caste.name = request.POST.get("name")
        parent_id = request.POST.get("parent")
        caste.parent = Caste.objects.get(id=parent_id) if parent_id else None
        caste.level = 'caste' if caste.parent else 'religion'
        caste.save()

        messages.success(request, "Updated successfully")
        return redirect('castes')

    religions = Caste.objects.filter(level='religion')
    return render(request, 'edit_caste_modal.html', {
        'caste': caste,
        'religions': religions
    })

def delete_caste(request, pk):
    caste = get_object_or_404(Caste, pk=pk)

    # Prevent deleting religion if castes exist
    if caste.level == 'religion' and caste.castes.exists():
        messages.error(request, "Cannot delete religion with castes")
        return redirect('castes')

    caste.delete()
    messages.success(request, "Deleted successfully")
    return redirect('castes')

def lifestyle_master(request):
    # Map of model types
    model_map = {
        "music_genre": MusicGenre,
        "music_activity": MusicActivity,
        "reading_preference": ReadingPreference,
        "movie_genre": MovieGenre,
        "story_banner": StoryBanner,  # Added banner
    }

    if request.method == "POST":
        action = request.POST.get("action")
        model_type = request.POST.get("model_type")
        name = request.POST.get("name")
        obj_id = request.POST.get("object_id")

        model_class = model_map.get(model_type)

        if not model_class:
            messages.error(request, "Invalid type")
            return redirect("lifestyle_master")

        # ➕ ADD
        if action == "add":
            if model_type == "story_banner":
                image = request.FILES.get("image")
                if not image:
                    messages.error(request, "Image is required")
                else:
                    model_class.objects.create(image=image)
                    messages.success(request, "Banner added successfully")
            else:
                if not name:
                    messages.error(request, "Name is required")
                else:
                    model_class.objects.create(name=name)
                    messages.success(request, "Added successfully")

        # ✏️ EDIT
        elif action == "edit":
            obj = get_object_or_404(model_class, id=obj_id)
            if model_type == "story_banner":
                image = request.FILES.get("image")
                if not image:
                    messages.error(request, "Image is required")
                else:
                    obj.image = image
                    obj.save()
                    messages.success(request, "Banner updated successfully")
            else:
                obj.name = name
                obj.save()
                messages.success(request, "Updated successfully")

        # 🗑 DELETE
        elif action == "delete":
            obj = get_object_or_404(model_class, id=obj_id)
            obj.delete()
            if model_type == "story_banner":
                messages.success(request, "Banner deleted successfully")
            else:
                messages.success(request, "Deleted successfully")

        return redirect("lifestyle_master")

    # ➡ Context for rendering
    context = {
        "music_genres": MusicGenre.objects.all(),
        "music_activities": MusicActivity.objects.all(),
        "reading_preferences": ReadingPreference.objects.all(),
        "movie_genres": MovieGenre.objects.all(),
        "story_banners": StoryBanner.objects.all(),  # Added banners
    }

    return render(request, "lifestyle_master.html", context)

def subscription_plans(request):

    if request.method == "POST":
        action = request.POST.get("action")

        # ADD / EDIT
        if action in ["add", "edit"]:
            plan_id = request.POST.get("plan_id")

            plan_name = request.POST.get("plan_name")
            price = request.POST.get("price")
            validity = request.POST.get("validity")
            description = request.POST.get("description")
            reveal_limit = request.POST.get("reveal_limit")
            is_active = request.POST.get("is_active") == "on"

            if action == "add":
                SubscriptionPlan.objects.create(
                    plan_name=plan_name,
                    price=price,
                    validity=validity,
                    description=description,
                    reveal_limit=reveal_limit,
                    is_active=is_active
                )
                messages.success(request, "Subscription plan added successfully")

            else:
                plan = get_object_or_404(SubscriptionPlan, id=plan_id)
                plan.plan_name = plan_name
                plan.price = price
                plan.validity = validity
                plan.description = description
                plan.reveal_limit = reveal_limit
                plan.is_active = is_active
                plan.save()

                messages.success(request, "Subscription plan updated successfully")

            return redirect("subscription_plans")

        # DELETE
        if action == "delete":
            plan_id = request.POST.get("plan_id")
            plan = get_object_or_404(SubscriptionPlan, id=plan_id)
            plan.delete()
            messages.success(request, "Subscription plan deleted")
            return redirect("subscription_plans")

    plans = SubscriptionPlan.objects.all()

    return render(request, "subscription_plans.html", {
        "plans": plans
    })

# def registered_user_list(request):
#     users = User.objects.filter(is_staff=False).order_by("-date_joined")
#     return render(request, "registered_user_list.html", {
#         "users": users
#     })

def user_list(request):
    users = CustomUser.objects.filter(is_staff=False, is_deleted=False).select_related("profile").annotate(
        is_premium=Exists(SubscriptionPayment.objects.filter(user=OuterRef('pk'), payment_status='success'))
    )

    # Filters
    gender = request.GET.get('gender')
    city = request.GET.get('city')
    state = request.GET.get('state')
    is_premium = request.GET.get('is_premium')
    has_profile_image = request.GET.get('has_profile_image')  # New filter

    if gender:
        users = users.filter(profile__gender=gender)
    if city:
        users = users.filter(profile__city__icontains=city)
    if state:
        users = users.filter(profile__state__icontains=state)
    if is_premium:
        users = users.filter(is_premium=bool(int(is_premium)))
    
    # New: Filter by profile image
    if has_profile_image:
        if has_profile_image == '1':  # Has profile image
            users = users.filter(profile_image__isnull=False)
        elif has_profile_image == '0':  # No profile image
            users = users.filter(profile_image__isnull=True)

    users = users.order_by("-date_joined")

    return render(request, "user_list.html", {
        "users": users
    })

def user_details(request, user_id):

    user = (
        CustomUser.objects
        .select_related("profile", "profile__lifestyle")
        .prefetch_related("user_images")
        .get(id=user_id)
    )

    subscription = (
        SubscriptionPayment.objects
        .filter(user=user, payment_status='success')
        .select_related('subscription')
        .order_by('-paid_at')
        .first()
    )

    return render(request, "user_details.html", {
        "user": user,
        "subscription": subscription,
        "now": timezone.now(),
    })

  # Only admins can toggle
@require_POST
def toggle_user_verified(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({
            "status": False,
            "message": "User not found",
            "response": []
        }, status=404)

    try:
        data = json.loads(request.body)
        is_verified = data.get("is_verified", None)
        if is_verified is None:
            return JsonResponse({
                "status": False,
                "message": "Missing 'is_verified' field",
                "response": []
            }, status=400)

        user.is_verified = bool(is_verified)
        user.save()

        return JsonResponse({
            "status": True,
            "message": f"User verification status updated to {user.is_verified}",
            "response": {"is_verified": user.is_verified}
        })

    except Exception as e:
        return JsonResponse({
            "status": False,
            "message": str(e),
            "response": []
        }, status=500)


@require_POST
def toggle_user_active(request, user_id):
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({
            "status": False,
            "message": "User not found",
            "response": []
        }, status=404)

    try:
        data = json.loads(request.body)
        is_active = data.get("is_active", None)
        if is_active is None:
            return JsonResponse({
                "status": False,
                "message": "Missing 'is_active' field",
                "response": []
            }, status=400)

        user.is_active = bool(is_active)
        user.save()

        return JsonResponse({
            "status": True,
            "message": f"User active status updated to {user.is_active}",
            "response": {"is_active": user.is_active}
        })

    except Exception as e:
        return JsonResponse({
            "status": False,
            "message": str(e),
            "response": []
        }, status=500)


def delete_user(request, user_id):
    from django.db import transaction
    user = get_object_or_404(CustomUser, id=user_id)
    try:
        with transaction.atomic():
            user.is_deleted = True
            user.deleted_at = timezone.now()
            user.is_active = False
            
            # Suffix email to release unique constraint for fresh registration
            suffix = f"_deleted_{int(timezone.now().timestamp())}"
            user.email = f"{user.email[:200]}{suffix}"
            
            user.save()
        messages.success(request, "User deleted successfully.")
    except Exception as e:
        messages.error(request, f"Error deleting user: {str(e)}")
    return redirect("user_list")


def sub_admin(request):
    sub_admins = CustomUser.objects.filter(role="sub_admin")

    sidebar_menus = SidebarMenu.objects.filter(is_active=True)

    for admin in sub_admins:
        admin.assigned_menu_ids = list(
            admin.menu_permissions.values_list("menu_id", flat=True)
        )

    return render(request, "sub_admin.html", {
        "sub_admins": sub_admins,
        "sidebar_menus": sidebar_menus
    })



def create_sub_admin(request):
    if request.method == "POST":

        email = request.POST.get("email")
        name = request.POST.get("name")
        password = request.POST.get("password")
        address = request.POST.get("address")

        profile_image = request.FILES.get("profile_image")
        aadhaar_card = request.FILES.get("aadhaar_card")

        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return redirect("sub_admin")

        CustomUser.objects.create(
            email=email,
            name=name,
            role="sub_admin",
            address=address,
            profile_image=profile_image,
            aadhaar_card=aadhaar_card,
            is_staff=True,
            is_active=True,
            password=make_password(password),
        )

        messages.success(request, "Sub Admin created successfully")
        return redirect("sub_admin")
    

def edit_sub_admin(request, sub_admin_id):
    sub_admin = get_object_or_404(CustomUser, id=sub_admin_id, role="sub_admin")

    if request.method == "POST":
        email = request.POST.get("email")
        name = request.POST.get("name")
        password = request.POST.get("password")
        address = request.POST.get("address")

        profile_image = request.FILES.get("profile_image")
        aadhaar_card = request.FILES.get("aadhaar_card")

        # Check email uniqueness, excluding current user
        if CustomUser.objects.filter(email=email).exclude(id=sub_admin_id).exists():
            messages.error(request, "Email already exists")
            return redirect("sub_admin")

        sub_admin.email = email
        sub_admin.name = name
        sub_admin.address = address

        if password:
            sub_admin.password = make_password(password)

        if profile_image:
            sub_admin.profile_image = profile_image

        if aadhaar_card:
            sub_admin.aadhaar_card = aadhaar_card

        sub_admin.save()

        messages.success(request, "Sub Admin updated successfully")
        return redirect("sub_admin")
    

def assign_sub_admin_menu(request, sub_admin_id):
    sub_admin = get_object_or_404(CustomUser, id=sub_admin_id, role="sub_admin")

    if request.method == "POST":
        menu_ids = request.POST.getlist("menus")

        # Remove old permissions
        SubAdminMenuPermission.objects.filter(sub_admin=sub_admin).delete()

        # Add new permissions
        permissions = [
            SubAdminMenuPermission(sub_admin=sub_admin, menu_id=menu_id)
            for menu_id in menu_ids
        ]
        SubAdminMenuPermission.objects.bulk_create(permissions)

        messages.success(request, "Menu permissions updated successfully")

    return redirect("sub_admin")


def delete_sub_admin(request, id):
    admin = get_object_or_404(CustomUser, id=id, role="sub_admin")
    admin.delete()
    messages.success(request, "Sub Admin deleted successfully")
    return redirect("sub_admin")


def compose_mail(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)

    if request.method == "POST":
        subject = request.POST.get("subject")
        message = request.POST.get("message")
        attachments = request.FILES.getlist("attachments")

        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )

        # 📎 Attach files
        for file in attachments:
            email.attach(file.name, file.read(), file.content_type)

        try:
            email.send()
            messages.success(request, "Email sent successfully!")
        except Exception as e:
            messages.error(request, f"Failed to send email: {str(e)}")

        return redirect("send_mail", user_id=user.id)

    return render(request, "compose_mail.html", {"user": user})


def blogs(request):
    if request.method == "POST":
        action = request.POST.get("action")
        
        # ADD / EDIT
        if action in ["add", "edit"]:
            blog_id = request.POST.get("blog_id")
            title = request.POST.get("title")
            short_description = request.POST.get("short_description")
            content = request.POST.get("content")
            status = request.POST.get("status")
            is_featured = request.POST.get("is_featured") == "on"
            cover_media = request.FILES.get("cover_media")
            cover_media_type = request.POST.get("cover_media_type")
            
            if action == "add":
                blog_data = {
                    "title": title,
                    "short_description": short_description,
                    "content": content,
                    "status": status,
                    "is_featured": is_featured
                }
                if cover_media and cover_media_type:
                    blog_data["cover_media"] = cover_media
                    blog_data["cover_media_type"] = cover_media_type
                
                Blog.objects.create(**blog_data)
                messages.success(request, "Blog created successfully")
            
            else:  # edit
                blog = get_object_or_404(Blog, id=blog_id)
                blog.title = title
                blog.short_description = short_description
                blog.content = content
                blog.status = status
                blog.is_featured = is_featured
                if cover_media and cover_media_type:
                    blog.cover_media = cover_media
                    blog.cover_media_type = cover_media_type
                blog.save()
                messages.success(request, "Blog updated successfully")
            
            return redirect("blogs")
        
        # DELETE
        if action == "delete":
            blog_id = request.POST.get("blog_id")
            blog = get_object_or_404(Blog, id=blog_id)
            blog.delete()
            messages.success(request, "Blog deleted successfully")
            return redirect("blogs")
    
    blogs = Blog.objects.all().order_by("-created_at")
    return render(request, "blogs.html", {
        "blogs": blogs
    })


def events(request):
    if request.method == "POST":
        action = request.POST.get("action")
        event_id = request.POST.get("event_id")
        event_name = request.POST.get("event_name")
        event_datetime = request.POST.get("event_datetime")
        venue = request.POST.get("venue")
        city = request.POST.get("city")
        description = request.POST.get("description")
        image = request.FILES.get("image")

        # ➕ ADD
        if action == "add":
            if not all([event_name, event_datetime, venue, city, image]):
                messages.error(request, "All fields including image are required!")
            else:
                Event.objects.create(
                    event_name=event_name,
                    event_datetime=event_datetime,
                    venue=venue,
                    city=city,
                    description=description,
                    image=image
                )
                messages.success(request, "Event added successfully!")

        # ✏️ EDIT
        elif action == "edit":
            obj = get_object_or_404(Event, id=event_id)
            obj.event_name = event_name
            obj.event_datetime = event_datetime
            obj.venue = venue
            obj.city = city
            obj.description = description
            if image:
                obj.image = image
            obj.save()
            messages.success(request, "Event updated successfully!")

        # 🗑 DELETE
        elif action == "delete":
            obj = get_object_or_404(Event, id=event_id)
            obj.delete()
            messages.success(request, "Event deleted successfully!")

        return redirect("events")

    context = {
        "events": Event.objects.all().order_by("-event_datetime")
    }
    return render(request, "events.html", context)


def success_story(request):
    stories = (
        SuccessStory.objects
        .select_related("created_by")
        .prefetch_related("images")
        .order_by("-created_at")
    )
    return render(request, 'success_story.html', {'stories': stories})


def delete_success_story(request, story_id):
    story = get_object_or_404(SuccessStory, id=story_id)
    story.delete()
    messages.success(request, "Success story deleted successfully.")
    return redirect("success_stories")

def revenue(request):

    selected_month = request.GET.get("month")
    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    payments = (
        SubscriptionPayment.objects
        .select_related("user", "subscription")
        .all()
    )

    # Month filter
    if selected_month:
        year, month = selected_month.split("-")
        payments = payments.filter(
            created_at__year=year,
            created_at__month=month
        )

    # From - To date filter
    if from_date:
        from_dt = make_aware(datetime.strptime(from_date, "%Y-%m-%d"))
        payments = payments.filter(created_at__gte=from_dt)

    if to_date:
        to_dt = make_aware(datetime.strptime(to_date, "%Y-%m-%d"))
        payments = payments.filter(created_at__lte=to_dt)

    # Statistics
    total_revenue = payments.filter(
        payment_status="success"
    ).aggregate(total=Sum("amount"))["total"] or 0

    success_count = payments.filter(payment_status="success").count()
    failed_count = payments.filter(payment_status="failed").count()

    context = {
        "payments": payments,
        "total_revenue": total_revenue,
        "success_count": success_count,
        "failed_count": failed_count,
        "selected_month": selected_month,
        "from_date": from_date,
        "to_date": to_date,
    }

    return render(request, "revenue.html", context)

def match_requests_list(request):
    match_requests = (
        MatchRequest.objects
        .select_related("from_user", "to_user")
        .all()
        .order_by("-created_at")
    )

    # Stats
    stats = (
        MatchRequest.objects
        .values("status")
        .annotate(count=Count("id"))
    )

    stats_map = {
        "total": match_requests.count(),
        "accepted": 0,
        "rejected": 0,
        "pending": 0,
        "cancelled": 0,
    }

    for item in stats:
        stats_map[item["status"]] = item["count"]

    context = {
        "match_requests": match_requests,
        "stats": stats_map,
    }

    return render(request, "match_requests.html", context)


def report_reasons(request):
    if request.method == "POST":
        action = request.POST.get("action")

        # ADD / EDIT
        if action in ["add", "edit"]:
            reason_id = request.POST.get("reason_id")

            title = request.POST.get("title")
          
            is_active = request.POST.get("is_active") == "on"

            if action == "add":
                ReportReason.objects.create(
                    title=title,
                    is_active=is_active
                )
                messages.success(request, "Report reason added successfully")

            else:
                reason = get_object_or_404(ReportReason, id=reason_id)
                reason.title = title
                reason.is_active = is_active
                reason.save()
                messages.success(request, "Report reason updated successfully")

            return redirect("report_reasons")

        # DELETE
        if action == "delete":
            reason_id = request.POST.get("reason_id")
            reason = get_object_or_404(ReportReason, id=reason_id)
            reason.delete()
            messages.success(request, "Report reason deleted")
            return redirect("report_reasons")

    reasons = ReportReason.objects.all().order_by("-created_at")

    return render(request, "report_reasons.html", {
        "reasons": reasons
    })


# forgot password
def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            messages.error(request, "No account found with this email.")
            return render(request, "forgot_password.html")

        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        reset_link = request.build_absolute_uri(f"/reset-password/{uid}/{token}/")

        # HTML email content
        subject = "Sindhuura Password Reset"
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.5;">
            <h2>Hi {user.name or user.email},</h2>
            <p>You requested a password reset for your Sindhuura account.</p>
            <p>
                Click the button below to reset your password:
            </p>
            <p>
                <a href="{reset_link}" style="padding: 10px 20px; background-color: #007bff; color: #fff; text-decoration: none; border-radius: 5px;">
                    Reset Password
                </a>
            </p>
            <p>If you did not request this, you can safely ignore this email.</p>
            <hr>
            <p style="font-size: 0.85em; color: #555;">Sindhuura Team</p>
        </body>
        </html>
        """

        email_message = EmailMultiAlternatives(
            subject=subject,
            body="Please use an HTML-compatible email client!",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email_message.attach_alternative(html_content, "text/html")
        email_message.send(fail_silently=False)

        messages.success(request, "Password reset link sent to your email.")
        return redirect("forgot_password")

    return render(request, "forgot_password.html")


# ----- Reset Password -----
def reset_password(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
        print(f"DEBUG: User found: {user.email}, ID: {uid}")  # Debug line
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        print(f"DEBUG: Error finding user: {e}")  # Debug line
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        print(f"DEBUG: Token check failed")
        messages.error(request, "The reset link is invalid or expired.")
        return redirect("forgot_password")

    if request.method == "POST":
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        if not password or not password2:
            messages.error(request, "Please enter both password fields.")
            return render(request, "reset_password.html")
        if password != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, "reset_password.html")

        user.set_password(password)
        user.is_active = True  # Ensure user is active after reset
        user.save()
        messages.success(request, "Password has been reset successfully! Please login.")
        return redirect("admin_login")

    return render(request, "reset_password.html")

def user_reports(request):
    if request.method == "POST":
        report_id = request.POST.get("report_id")
        new_status = request.POST.get("status")
        report = get_object_or_404(UserReport, id=report_id)

        report.status = new_status
        report.save()
        messages.success(request, f"Report status updated to {new_status.replace('_', ' ').title()}")
        return redirect("user_reports")  # reload page to reflect change

    reports = UserReport.objects.select_related(
        "reported_by", "reported_user", "reason"
    )
    return render(request, "user_reports.html", {
        "reports": reports
    })