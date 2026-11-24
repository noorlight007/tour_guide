from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import GuestUser, User
from tour_plan.models import Booking, BookingItem, CartItem, TimeSlot, TourDate, TourPlan


class BookingContactTests(TestCase):
    email = "booking@example.com"
    whatsapp = "+12025550123"
    profile_whatsapp = "+442083661177"

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            username="member@example.com",
            email="member@example.com",
            whatsapp=self.profile_whatsapp,
        )
        self.admin = User.objects.create(
            username="admin@example.com",
            email="admin@example.com",
            whatsapp="+12025550124",
            role="ADMIN",
        )
        self.tour = TourPlan.objects.create(
            title="Rome walking tour",
            description="A tour for booking contact tests",
            max_adults=10,
            price_adult=Decimal("50"),
        )
        tour_date = TourDate.objects.create(tour_plan=self.tour, date=date(2030, 1, 1))
        self.slot = TimeSlot.objects.create(
            tour_date=tour_date,
            start_time=time(10),
            available_adults=10,
            available_children=0,
            available_infants=0,
        )

    def book_now_payload(self, **updates):
        payload = {
            "full_name": "Booking Traveler",
            "email": self.email,
            "whatsapp": self.whatsapp,
            "country": "Italy",
            "traveler_details": [],
            "book_now": True,
            "single_item": {
                "tour_plan": self.tour.pk,
                "time_slot": self.slot.pk,
                "num_adults": 2,
            },
        }
        payload.update(updates)
        return payload

    def cart_payload(self, item, **updates):
        payload = self.book_now_payload(**updates)
        payload.pop("single_item")
        payload["book_now"] = False
        payload["cart_item_ids"] = [item.pk]
        return payload

    def create_cart(self, user=None):
        return CartItem.objects.create(
            user=user,
            tour_plan=self.tour,
            time_slot=self.slot,
            num_adults=2,
        )

    def post_booking(self, payload):
        return self.client.post(reverse("booking-list-create"), payload, format="json")

    def assert_contact_snapshot(self, response, email=None, whatsapp=None):
        email = self.email if email is None else email
        whatsapp = self.whatsapp if whatsapp is None else whatsapp
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["email"], email)
        self.assertEqual(response.data["whatsapp"], whatsapp)
        booking = Booking.objects.get(pk=response.data["id"])
        self.assertEqual(booking.email, email)
        self.assertEqual(str(booking.whatsapp), whatsapp)
        return booking

    def test_new_bookings_require_valid_explicit_contacts_for_every_user_type(self):
        missing = object()
        invalid_values = {
            "email": (
                missing, "", None, "not-an-email", "guest@", "a" * 245 + "@example.com"
            ),
            "whatsapp": (
                missing, "", None, "not-a-number", "+999123456789", "2025550123"
            ),
        }
        for actor in (None, self.customer, self.admin):
            self.client.force_authenticate(user=actor)
            for field, values in invalid_values.items():
                for value in values:
                    with self.subTest(actor=actor, field=field, value=value):
                        payload = self.book_now_payload()
                        if value is missing:
                            payload.pop(field)
                        else:
                            payload[field] = value

                        response = self.post_booking(payload)

                        self.assertEqual(response.status_code, 400, response.data)
                        self.assertIn(field, response.data)
                        self.assertEqual(Booking.objects.count(), 0)
                        self.assertEqual(BookingItem.objects.count(), 0)
                        self.assertEqual(GuestUser.objects.count(), 0)
                        self.assertEqual(User.objects.count(), 2)
                        self.slot.refresh_from_db()
                        self.assertEqual(self.slot.available_adults, 10)
        self.customer.refresh_from_db()
        self.assertEqual(str(self.customer.whatsapp), self.profile_whatsapp)

    def test_cart_checkout_rejects_missing_contacts_without_consuming_cart(self):
        for actor in (None, self.customer):
            self.client.force_authenticate(user=actor)
            item = self.create_cart(user=actor)
            with self.subTest(actor=actor):
                payload = self.cart_payload(item)
                payload.pop("email")
                payload.pop("whatsapp")

                response = self.post_booking(payload)

                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("email", response.data)
                self.assertIn("whatsapp", response.data)
                self.assertTrue(CartItem.objects.filter(pk=item.pk).exists())
                self.assertEqual(Booking.objects.count(), 0)
                self.assertEqual(BookingItem.objects.count(), 0)
                self.assertEqual(GuestUser.objects.count(), 0)
                self.slot.refresh_from_db()
                self.assertEqual(self.slot.available_adults, 10)

    def test_guest_book_now_exposes_contact_snapshot_in_create_list_and_details(self):
        booking = self.assert_contact_snapshot(self.post_booking(self.book_now_payload()))
        self.assertEqual(booking.user_type, "guest")
        self.assertEqual(booking.guest_user.email, self.email)
        self.assertIsNone(booking.guest_user.phone)
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(reverse("booking-list-create"))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["email"], self.email)
        self.assertEqual(response.data["results"][0]["whatsapp"], self.whatsapp)

        response = self.client.get(reverse("booking-detail", args=[booking.pk]))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["email"], self.email)
        self.assertEqual(response.data["whatsapp"], self.whatsapp)

    def test_guest_cart_checkout_persists_contact_snapshot(self):
        item = self.create_cart()

        booking = self.assert_contact_snapshot(self.post_booking(self.cart_payload(item)))

        self.assertEqual(booking.user_type, "guest")
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())

    def test_authenticated_book_now_uses_submitted_contacts_without_changing_profile(self):
        self.client.force_authenticate(user=self.customer)

        booking = self.assert_contact_snapshot(self.post_booking(self.book_now_payload()))

        self.assertEqual(booking.user_id, self.customer.pk)
        self.assertEqual(booking.user_type, "user")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, "member@example.com")
        self.assertEqual(str(self.customer.whatsapp), self.profile_whatsapp)

    def test_authenticated_cart_checkout_persists_submitted_contact_snapshot(self):
        self.client.force_authenticate(user=self.customer)
        item = self.create_cart(user=self.customer)

        booking = self.assert_contact_snapshot(self.post_booking(self.cart_payload(item)))

        self.assertEqual(booking.user_id, self.customer.pk)
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())

    def test_admin_booking_persists_the_travelers_contact_snapshot(self):
        self.client.force_authenticate(user=self.admin)

        booking = self.assert_contact_snapshot(self.post_booking(self.book_now_payload()))

        self.assertTrue(booking.booked_by_admin)
        self.assertEqual(booking.user_type, "guest")
        self.assertEqual(booking.guest_user.email, self.email)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "admin@example.com")
        self.assertEqual(str(self.admin.whatsapp), "+12025550124")

    def test_admin_booking_for_existing_user_keeps_submitted_contact_snapshot(self):
        self.client.force_authenticate(user=self.admin)
        response = self.post_booking(self.book_now_payload(email=self.customer.email))

        booking = self.assert_contact_snapshot(response, email=self.customer.email)

        self.assertTrue(booking.booked_by_admin)
        self.assertEqual(booking.user_id, self.customer.pk)
        self.assertEqual(booking.user_type, "user")
        self.assertIsNone(booking.guest_user_id)
        self.assertEqual(GuestUser.objects.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, "member@example.com")
        self.assertEqual(str(self.customer.whatsapp), self.profile_whatsapp)
        self.assertIsNone(self.customer.phone)

    def test_guest_matching_existing_email_keeps_submitted_number_and_profile_unchanged(self):
        response = self.post_booking(self.book_now_payload(email=self.customer.email))

        booking = self.assert_contact_snapshot(response, email=self.customer.email)

        self.assertEqual(booking.user_id, self.customer.pk)
        self.assertEqual(booking.user_type, "user")
        self.assertIsNone(booking.guest_user_id)
        self.assertEqual(GuestUser.objects.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(str(self.customer.whatsapp), self.profile_whatsapp)
        self.assertIsNone(self.customer.phone)
        self.customer.whatsapp = "+12025550125"
        self.customer.save(update_fields=["whatsapp"])
        self.client.force_authenticate(user=self.customer)

        response = self.client.get(reverse("booking-detail", args=[booking.pk]))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["email"], self.customer.email)
        self.assertEqual(response.data["whatsapp"], self.whatsapp)

    def test_optional_phone_is_separate_from_required_whatsapp(self):
        response = self.post_booking(self.book_now_payload(phone=self.profile_whatsapp))

        booking = self.assert_contact_snapshot(response)

        self.assertEqual(booking.guest_user.phone, self.profile_whatsapp)
        self.assertNotEqual(booking.guest_user.phone, str(booking.whatsapp))

    def test_legacy_status_patch_does_not_require_contact_backfill(self):
        booking = Booking.objects.create(user=self.customer)
        self.client.force_authenticate(user=self.customer)

        response = self.client.patch(
            reverse("booking-detail", args=[booking.pk]),
            {"status": "accepted"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "accepted")
        self.assertEqual(booking.email, "")
        self.assertFalse(booking.whatsapp)
