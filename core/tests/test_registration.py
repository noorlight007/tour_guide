from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import User


class RegistrationContactTests(APITestCase):
    def setUp(self):
        self.url = reverse("user-registration")
        self.payload = {
            "email": "traveler@example.com",
            "whatsapp": "+1 202 555 0123",
            "password": "registration-test-password",
            "first_name": "Test",
            "last_name": "Traveler",
        }

    def test_email_and_whatsapp_are_required(self):
        for field in ("email", "whatsapp"):
            with self.subTest(field=field):
                payload = self.payload.copy()
                payload.pop(field)

                response = self.client.post(self.url, payload, format="json")

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data)
                self.assertFalse(User.objects.exists())

    def test_email_and_whatsapp_reject_blank_null_and_invalid_values(self):
        invalid_values = {
            "email": ("", "   ", None, "invalid-email"),
            "whatsapp": ("", "   ", None, "invalid-number", "+123"),
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.post(
                        self.url, {**self.payload, field: value}, format="json"
                    )

                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn(field, response.data)
                    self.assertFalse(User.objects.exists())

    def test_registration_persists_normalized_contacts_without_requiring_phone(self):
        response = self.client.post(
            self.url,
            {**self.payload, "email": "Traveler@Example.COM"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get()
        self.assertEqual(user.email, "traveler@example.com")
        self.assertEqual(user.username, "traveler@example.com")
        self.assertEqual(user.whatsapp.as_e164, "+12025550123")
        self.assertIsNone(user.phone)
        self.assertTrue(user.check_password(self.payload["password"]))

    def test_email_longer_than_user_storage_limit_is_rejected(self):
        oversized_email = "a" * 64 + "@" + ".".join(
            ("b" * 63, "c" * 63, "d" * 58, "com")
        )
        self.assertEqual(len(oversized_email), 255)

        response = self.client.post(
            self.url,
            {**self.payload, "email": oversized_email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"][0].code, "max_length")
        self.assertFalse(User.objects.exists())

    def test_phone_is_optional_and_separate_from_whatsapp(self):
        response = self.client.post(
            self.url,
            {**self.payload, "phone": "+12025550124"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get()
        self.assertEqual(user.phone.as_e164, "+12025550124")
        self.assertEqual(user.whatsapp.as_e164, "+12025550123")

    def test_phone_does_not_replace_required_whatsapp(self):
        payload = {**self.payload, "phone": "+12025550124"}
        payload.pop("whatsapp")

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("whatsapp", response.data)
        self.assertFalse(User.objects.exists())

    def test_existing_email_is_rejected_case_insensitively(self):
        User.objects.create(
            email="Traveler@Example.COM", username="existing-traveler"
        )

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(User.objects.count(), 1)

    def test_equivalent_whatsapp_format_is_rejected_as_duplicate(self):
        User.objects.create(
            email="existing@example.com",
            username="existing-traveler",
            whatsapp="+12025550123",
        )

        response = self.client.post(
            self.url,
            {**self.payload, "whatsapp": "+1 (202) 555-0123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("whatsapp", response.data)
        self.assertEqual(User.objects.count(), 1)
