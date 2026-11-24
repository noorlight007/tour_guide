from datetime import date, time
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from core.models import User
from tour_plan.models import Booking, BookingItem, CartItem, TimeSlot, TourDate, TourPlan
from tour_plan.rest.serializers.booking import BookingItemSerializer


class TravelerCountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tour = TourPlan.objects.create(
            title="Rome walking tour",
            description="A tour with five traveler categories",
            max_adults=8,
            max_children=8,
            max_infants=8,
            max_youth=8,
            max_student_eu=8,
            price_adult=Decimal("50"),
            price_child=Decimal("20"),
            price_infant=Decimal("5"),
            price_youth=Decimal("30"),
            price_student_eu=Decimal("25"),
        )
        tour_date = TourDate.objects.create(tour_plan=self.tour, date=date(2030, 1, 1))
        self.slot = TimeSlot.objects.create(
            tour_date=tour_date,
            start_time=time(10),
            available_adults=8,
            available_children=8,
            available_infants=8,
            available_youth=8,
            available_student_eu=8,
        )

    def create_cart_item(self):
        return CartItem.objects.create(
            tour_plan=self.tour,
            time_slot=self.slot,
            num_adults=1,
            num_youth=1,
            num_student_eu=1,
        )

    def create_booking_item(self):
        admin = User.objects.create_user(email="admin@example.com")
        admin.role = "ADMIN"
        admin.save(update_fields=["role"])
        self.client.force_authenticate(admin)
        booking = Booking.objects.create()
        item = BookingItem.objects.create(
            booking=booking,
            tour_plan=self.tour,
            time_slot=self.slot,
            num_adults=1,
            num_youth=1,
            num_student_eu=1,
        )
        booking.total_price = item.item_price
        booking.save()
        return item

    def test_guest_cart_includes_youth_and_student_prices(self):
        response = self.client.post(
            reverse("cart-item-list-create"),
            {
                "tour_plan": self.tour.pk,
                "time_slot": self.slot.pk,
                "num_adults": 1,
                "num_youth": 1,
                "num_student_eu": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["item_price"]), Decimal("105"))

    def test_guest_can_change_all_traveler_counts_in_cart(self):
        item = self.create_cart_item()
        response = self.client.patch(
            reverse("cart-item-detail", args=[item.pk]),
            {
                "num_adults": 2,
                "num_children": 1,
                "num_infants": 1,
                "num_youth": 2,
                "num_student_eu": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        item.refresh_from_db()
        self.assertEqual(item.num_adults, 2)
        self.assertEqual(item.num_children, 1)
        self.assertEqual(item.num_infants, 1)
        self.assertEqual(item.num_youth, 2)
        self.assertEqual(item.num_student_eu, 2)
        self.assertEqual(item.item_price, Decimal("235"))
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.available_adults, 8)

    def test_cart_rejects_count_above_remaining_capacity(self):
        item = self.create_cart_item()
        response = self.client.patch(
            reverse("cart-item-detail", args=[item.pk]),
            {"num_youth": 9},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        item.refresh_from_db()
        self.assertEqual(item.num_youth, 1)

    def test_guest_checkout_recalculates_legacy_cart_price(self):
        item = self.create_cart_item()
        CartItem.objects.filter(pk=item.pk).update(item_price=Decimal("50"))
        response = self.client.post(
            reverse("booking-list-create"),
            {
                "full_name": "Guest Traveler",
                "email": "guest@example.com",
                "whatsapp": "+12025550123",
                "country": "Italy",
                "traveler_details": [],
                "cart_item_ids": [item.pk],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = Booking.objects.get(pk=response.data["id"])
        booking_item = booking.booking_items.get()
        self.assertEqual(booking_item.num_youth, 1)
        self.assertEqual(booking_item.num_student_eu, 1)
        self.assertEqual(booking_item.item_price, Decimal("105"))
        self.assertEqual(booking.total_price, Decimal("105"))
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())

    def test_guest_book_now_preserves_all_five_traveler_counts(self):
        counts = {
            "num_adults": 2,
            "num_children": 1,
            "num_infants": 1,
            "num_youth": 2,
            "num_student_eu": 2,
        }
        response = self.client.post(
            reverse("booking-list-create"),
            {
                "full_name": "Guest Traveler",
                "email": "guest@example.com",
                "whatsapp": "+12025550123",
                "country": "Italy",
                "traveler_details": [],
                "book_now": True,
                "single_item": {
                    "tour_plan": self.tour.pk,
                    "time_slot": self.slot.pk,
                    **counts,
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = Booking.objects.get(pk=response.data["id"])
        booking_item = booking.booking_items.get()
        for field, count in counts.items():
            self.assertEqual(getattr(booking_item, field), count)
        self.assertEqual(booking_item.item_price, Decimal("235"))
        self.assertEqual(booking.total_price, Decimal("235"))
        self.slot.refresh_from_db()
        for field, count in counts.items():
            self.assertEqual(getattr(self.slot, field.replace("num_", "available_")), 8 - count)

    def test_booking_count_update_recalculates_prices_and_capacity(self):
        item = self.create_booking_item()
        BookingItem.objects.create(
            booking=item.booking,
            tour_plan=self.tour,
            time_slot=self.slot,
            num_adults=1,
        )
        response = self.client.patch(
            reverse("booking-item-details", args=[item.pk]),
            {
                "num_adults": 2,
                "num_children": 1,
                "num_infants": 1,
                "num_youth": 2,
                "num_student_eu": 2,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        item.refresh_from_db()
        item.booking.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual(item.item_price, Decimal("235"))
        self.assertEqual(item.booking.total_price, Decimal("285"))
        for category in ("adults", "children", "infants", "youth", "student_eu"):
            self.assertEqual(getattr(self.slot, f"available_{category}"), 7)

    def test_reducing_booking_count_returns_capacity_and_recalculates_price(self):
        item = self.create_booking_item()
        response = self.client.patch(
            reverse("booking-item-details", args=[item.pk]),
            {"num_youth": 0, "num_student_eu": 0},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        item.refresh_from_db()
        item.booking.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual(item.item_price, Decimal("50"))
        self.assertEqual(item.booking.total_price, Decimal("50"))
        self.assertEqual(self.slot.available_youth, 9)
        self.assertEqual(self.slot.available_student_eu, 9)

    def test_booking_rechecks_capacity_when_saving_count_change(self):
        item = self.create_booking_item()
        serializer = BookingItemSerializer(
            item, data={"num_adults": 2}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        TimeSlot.objects.filter(pk=self.slot.pk).update(available_adults=0)

        with self.assertRaises(ValidationError):
            serializer.save()

        item.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual(item.num_adults, 1)
        self.assertEqual(self.slot.available_adults, 0)
