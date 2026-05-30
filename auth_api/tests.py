from django.test import TestCase
from django.utils import timezone
from auth_api.models import CustomUser, PhoneOTP
from backend.models import Caste
from django.urls import reverse
from rest_framework import status

class UserReRegistrationTests(TestCase):
    def setUp(self):
        self.religion = Caste.objects.create(name="Hindu", level="religion")
        self.caste = Caste.objects.create(name="Brahmin", level="caste", parent=self.religion)
        
        self.register_data = {
            "email": "testrereg@example.com",
            "password": "Password123",
            "confirm_password": "Password123",
            "phone_number": "9876543210",
            "name": "Test User",
            "this_account_for": "myself",
            "mother_tongue": "Kannada",
            "gender": "male",
            "date_of_birth": "1995-01-01",
            "height": "5.5",
            "physical_status": "normal",
            "marital_status": "never_married",
            "religion": self.religion.id,
            "caste": self.caste.id,
            "willing_inter_caste": True,
            "education": "bachelors",
            "field_of_study": "Computer Science",
            "occupation": "software",
            "annual_income": "5-10",
            "country": "India",
            "state": "Karnataka",
            "city": "Bengaluru",
            "family_status": "middle",
            "family_worth": "10-25",
            "terms_accepted": True,
        }

    def test_user_re_registration_flow(self):
        # 1. Register a user
        url_register = reverse('register')
        response = self.client.post(url_register, self.register_data, content_type='application/json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify user is created in database
        self.assertTrue(CustomUser.objects.filter(email="testrereg@example.com").exists())
        
        # 2. Try to check if email/phone exists (should be True)
        url_check_email = reverse('check-email')
        response_check = self.client.post(url_check_email, {
            "email": "testrereg@example.com",
            "phone_number": "+919876543210" # system auto-formats 9876543210 to +919876543210
        }, content_type='application/json')
        self.assertEqual(response_check.status_code, status.HTTP_200_OK)
        self.assertTrue(response_check.json()['response']['email_exists'])
        self.assertTrue(response_check.json()['response']['phone_exists'])
        
        # 3. Soft-delete the user
        user = CustomUser.objects.get(email="testrereg@example.com")
        # Create verified PhoneOTP first because DeleteAccountSerializer requires verified OTP
        otp_obj = PhoneOTP.objects.create(
            phone_number="+919876543210",
            otp="123456",
            is_verified=False
        )
        # Verify the OTP via API
        url_verify_otp = reverse('verify-otp')
        self.client.post(url_verify_otp, {
            "phone_number": "9876543210",
            "otp": "123456"
        }, content_type='application/json')
        
        # Perform delete-account via DeleteAccountAPIView
        url_delete_account = reverse('delete-account')
        response_delete = self.client.post(url_delete_account, {
            "phone_number": "9876543210",
            "otp": "123456"
        }, content_type='application/json')
        self.assertEqual(response_delete.status_code, status.HTTP_200_OK)
        
        # Verify user in database has is_deleted=True and is_active=False
        user.refresh_from_db()
        self.assertTrue(user.is_deleted)
        self.assertFalse(user.is_active)
        self.assertTrue(user.email.endswith("_deleted_" + str(int(user.deleted_at.timestamp()))))
        
        # 4. Check if email/phone exists for deleted account (should be False)
        response_check_2 = self.client.post(url_check_email, {
            "email": "testrereg@example.com",
            "phone_number": "9876543210"
        }, content_type='application/json')
        self.assertEqual(response_check_2.status_code, status.HTTP_200_OK)
        self.assertFalse(response_check_2.json()['response']['email_exists'])
        self.assertFalse(response_check_2.json()['response']['phone_exists'])
        
        # 5. Try to login with deleted user credentials (should return 403 Forbidden with deleted warning message)
        url_login = reverse('login')
        response_login = self.client.post(url_login, {
            "email": "testrereg@example.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response_login.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("This account has been deleted", response_login.json()['errors'])
        
        # 6. Re-register the same email/phone (should succeed!)
        response_rereg = self.client.post(url_register, self.register_data, content_type='application/json')
        self.assertEqual(response_rereg.status_code, status.HTTP_201_CREATED)
        
        # Verify there are now two user records in the DB:
        # one deleted (with suffix email) and one active
        self.assertEqual(CustomUser.objects.filter(is_deleted=True).count(), 1)
        self.assertEqual(CustomUser.objects.filter(is_deleted=False, email="testrereg@example.com").count(), 1)
        
        # 7. Login with the new active user credentials (should succeed!)
        response_login_active = self.client.post(url_login, {
            "email": "testrereg@example.com",
            "password": "Password123"
        }, content_type='application/json')
        self.assertEqual(response_login_active.status_code, status.HTTP_200_OK)
        self.assertIn("access_token", response_login_active.json()['data'])

    def test_admin_deletion_flow(self):
        # 1. Register a user
        url_register = reverse('register')
        self.client.post(url_register, self.register_data, content_type='application/json')
        user = CustomUser.objects.get(email="testrereg@example.com")
        
        # 2. Admin deletes user
        # Note: We simulate admin delete view call
        url_admin_delete = reverse('delete_user', args=[user.id])
        response = self.client.post(url_admin_delete) # delete_user redirects to user_list
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        
        # Verify user is soft-deleted and email suffixed
        user.refresh_from_db()
        self.assertTrue(user.is_deleted)
        self.assertFalse(user.is_active)
        self.assertTrue(user.email.endswith("_deleted_" + str(int(user.deleted_at.timestamp()))))
        
        # 3. Verify re-registration succeeds
        response_rereg = self.client.post(url_register, self.register_data, content_type='application/json')
        self.assertEqual(response_rereg.status_code, status.HTTP_201_CREATED)
