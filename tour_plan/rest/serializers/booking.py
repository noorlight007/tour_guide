import decimal
import json
import logging
import re
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Sum
from django.template.loader import render_to_string
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from core.models import GuestUser, User
from tour_plan.models import Booking, BookingItem, CartItem, TimeSlot
from tour_plan.rest.serializers.tour_plan import TourPlanSerializer
from tour_plan.rest.serializers.tour_time import TimeSlotSerializer

logger = logging.getLogger(__name__)


def _format_travelers(raw):
    """Turns traveler_details (list/dict/JSON string) into rows for the email."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return [{"name": raw, "extras": []}] if raw.strip() else []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    travelers = []
    for entry in raw:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("full_name") or "-"
            extras = [
                {"label": str(key).replace("_", " ").capitalize(), "value": value}
                for key, value in entry.items()
                if key not in ("name", "full_name") and value not in (None, "")
            ]
            travelers.append({"name": name, "extras": extras})
        elif entry not in (None, ""):
            travelers.append({"name": str(entry), "extras": []})
    return travelers


def _build_booking_email_context(booking):
    items = BookingItem.objects.filter(booking=booking).select_related(
        "tour_plan", "time_slot"
    )

    item_rows = []
    for item in items:
        parts = [
            f"{count} {label}"
            for label, count in (
                ("Adults", item.num_adults),
                ("Children", item.num_children),
                ("Youth", item.num_youth),
                ("Infants", item.num_infants),
                ("EU students", item.num_student_eu),
            )
            if count
        ]
        item_rows.append(
            {
                "tour": str(item.tour_plan),
                "slot": str(item.time_slot),
                "participants": ", ".join(parts) or "-",
                "price": item.item_price,
            }
        )

    guest = getattr(booking, "guest_user", None)
    user = getattr(booking, "user", None)
    customer_name = getattr(guest, "full_name", None)
    if not customer_name and user is not None and hasattr(user, "get_full_name"):
        customer_name = user.get_full_name()
    customer_name = customer_name or booking.email

    country = getattr(guest, "country", None) or getattr(user, "country", None)

    return {
        "booking": booking,
        "items": item_rows,
        "customer_name": customer_name,
        "customer_type": booking.user_type,
        "booked_by_admin": getattr(booking, "booked_by_admin", False),
        "country": country,
        "whatsapp_digits": re.sub(r"\D", "", str(booking.whatsapp)),
        "travelers": _format_travelers(booking.traveler_details),
        "created_at": getattr(booking, "created_at", None),
    }


def _send_booking_notification(booking_id):
    """Builds and sends the new-booking email. Never raises."""
    try:
        booking = Booking.objects.get(id=booking_id)
        context = _build_booking_email_context(booking)

        text_body = render_to_string("emails/booking_notification.txt", context)
        html_body = render_to_string("emails/booking_notification.html", context)

        email = EmailMultiAlternatives(
            subject=f"New Booking #{booking.id} - {context['customer_name']}",
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.BOOKING_NOTIFICATION_EMAIL],
            reply_to=[booking.email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=False)
    except Exception:
        logger.exception(
            "Failed to send booking notification for booking %s", booking_id
        )


def send_booking_notification(booking_id):
    # Background thread so the API response isn't delayed by SMTP
    threading.Thread(
        target=_send_booking_notification, args=(booking_id,), daemon=True
    ).start()


class BookingItemSerializer(serializers.ModelSerializer):
    time_slot = TimeSlotSerializer(read_only=True)

    class Meta:
        model = BookingItem
        fields = "__all__"
        read_only_fields = ["id", "booking"]

    def validate(self, attrs):
        instance = self.instance
        if not instance:
            return attrs
        new_adults = attrs.get("num_adults", instance.num_adults)
        new_children = attrs.get("num_children", instance.num_children)
        new_infants = attrs.get("num_infants", instance.num_infants)
        new_youth = attrs.get("num_youth", instance.num_youth)
        new_student_eu = attrs.get("num_student_eu", instance.num_student_eu)
        diff_adults = new_adults - instance.num_adults
        diff_children = new_children - instance.num_children
        diff_infants = new_infants - instance.num_infants
        diff_youth = new_youth - instance.num_youth
        diff_student_eu = new_student_eu - instance.num_student_eu

        time_slot = instance.time_slot
        if (
            (diff_adults > 0 and time_slot.available_adults < diff_adults)
            or (diff_children > 0 and time_slot.available_children < diff_children)
            or (diff_infants > 0 and time_slot.available_infants < diff_infants)
            or (diff_youth > 0 and time_slot.available_youth < diff_youth)
            or (
                diff_student_eu > 0 and time_slot.available_student_eu < diff_student_eu
            )
        ):
            raise serializers.ValidationError(
                "Not enough availability in selected time slot."
            )

        return attrs

    def update(self, instance, validated_data):
        with transaction.atomic():
            time_slot = TimeSlot.objects.select_for_update().get(
                id=instance.time_slot.id
            )
            new_adults = validated_data.get("num_adults", instance.num_adults)
            new_children = validated_data.get("num_children", instance.num_children)
            new_infants = validated_data.get("num_infants", instance.num_infants)
            new_youth = validated_data.get("num_youth", instance.num_youth)
            new_student_eu = validated_data.get(
                "num_student_eu", instance.num_student_eu
            )
            diff_adults = new_adults - instance.num_adults
            diff_children = new_children - instance.num_children
            diff_infants = new_infants - instance.num_infants
            diff_youth = new_youth - instance.num_youth
            diff_student_eu = new_student_eu - instance.num_student_eu

            if not time_slot.has_availability(
                adults=max(diff_adults, 0),
                children=max(diff_children, 0),
                infants=max(diff_infants, 0),
                youth=max(diff_youth, 0),
                student_eu=max(diff_student_eu, 0),
            ):
                raise serializers.ValidationError(
                    "Not enough availability in selected time slot."
                )

            time_slot.available_adults -= diff_adults
            time_slot.available_children -= diff_children
            time_slot.available_infants -= diff_infants
            time_slot.available_youth -= diff_youth
            time_slot.available_student_eu -= diff_student_eu

            time_slot.save()

            counts_changed = any(
                difference != 0
                for difference in (
                    diff_adults,
                    diff_children,
                    diff_infants,
                    diff_youth,
                    diff_student_eu,
                )
            )
            if counts_changed:
                instance.num_adults = new_adults
                instance.num_children = new_children
                instance.num_infants = new_infants
                instance.num_youth = new_youth
                instance.num_student_eu = new_student_eu
                validated_data["item_price"] = instance.calculate_item_price()

            instance = super().update(instance, validated_data)
            if counts_changed or "item_price" in validated_data:
                booking = Booking.objects.select_for_update().get(
                    id=instance.booking_id
                )
                booking.total_price = booking.booking_items.aggregate(
                    total=Sum("item_price")
                )["total"] or decimal.Decimal(0)
                booking.save(update_fields=["total_price", "updated_at"])
            return instance


class BookingItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingItem
        fields = "__all__"
        read_only_fields = ["id", "booking"]


class BookingSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    full_name = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(required=True, max_length=254)
    whatsapp = PhoneNumberField(
        required=True,
        help_text="WhatsApp number including the international country code.",
    )
    country = serializers.CharField(write_only=True, required=False)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    book_now = serializers.BooleanField(write_only=True, required=False)
    single_item = BookingItemCreateSerializer(write_only=True, required=False)

    class Meta:
        model = Booking
        fields = "__all__"
        read_only_fields = ["id", "user", "total_price"]

    def get_items(self, object):
        items = BookingItem.objects.filter(booking=object)
        return BookingItemSerializer(items, many=True).data

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        status = attrs.get("status")
        cancelled_reason = attrs.get("cancelled_reason")

        if status == "cancelled" and (
            not cancelled_reason or len(cancelled_reason) <= 0
        ):
            raise serializers.ValidationError(
                {
                    "cancelled_reason": "Cancelled reason is required when status is cancelled."
                }
            )

        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            contact_details = {
                "email": validated_data.pop("email"),
                "whatsapp": validated_data.pop("whatsapp"),
            }
            user_type = "guest"
            is_book_now = validated_data.pop("book_now", None)
            single_item = validated_data.pop("single_item", None)
            if self.context["request"].user.is_authenticated:
                user_type = "user"

            traveler_details = validated_data.pop("traveler_details")
            if user_type == "user":
                user = self.context["request"].user
                if user.role in ["ADMIN", "SUPER_ADMIN"]:
                    full_name = validated_data.pop("full_name")
                    email = contact_details["email"]
                    country = validated_data.pop("country")
                    phone = validated_data.pop("phone", None)
                    user = User.objects.filter(email__iexact=email)
                    if not user.exists():
                        guest_user = GuestUser.objects.create(
                            full_name=full_name,
                            email=email,
                            country=country,
                            phone=phone,
                        )
                        booking = Booking.objects.create(
                            guest_user=guest_user,
                            user_type="guest",
                            traveler_details=traveler_details,
                            booked_by_admin=True,
                            **contact_details,
                        )
                    else:
                        booking = Booking.objects.create(
                            user=user.first(),
                            user_type="user",
                            traveler_details=traveler_details,
                            booked_by_admin=True,
                            **contact_details,
                        )
                else:
                    booking = Booking.objects.create(
                        user=user,
                        user_type=user_type,
                        traveler_details=traveler_details,
                        **contact_details,
                    )
                if not is_book_now:
                    cartitems = CartItem.objects.filter(user=user)
            else:
                full_name = validated_data.pop("full_name")
                email = contact_details["email"]
                country = validated_data.pop("country")
                phone = validated_data.pop("phone", None)
                user = User.objects.filter(email__iexact=email)
                if not user.exists():
                    guest_user = GuestUser.objects.create(
                        full_name=full_name, email=email, country=country, phone=phone
                    )
                    booking = Booking.objects.create(
                        guest_user=guest_user,
                        user_type="guest",
                        traveler_details=traveler_details,
                        **contact_details,
                    )
                else:
                    booking = Booking.objects.create(
                        user=user.first(),
                        user_type="user",
                        traveler_details=traveler_details,
                        **contact_details,
                    )
                if not is_book_now:
                    cart_item_ids = validated_data.pop("cart_item_ids")
                    cartitems = CartItem.objects.filter(id__in=cart_item_ids)

            if not is_book_now:
                total_price = decimal.Decimal(0)
                order_items_to_create = []
                for item in cartitems:
                    item_price = item.calculate_item_price()
                    total_price += item_price
                    order_items_to_create.append(
                        BookingItem(
                            booking=booking,
                            tour_plan=item.tour_plan,
                            time_slot=item.time_slot,
                            num_adults=item.num_adults,
                            num_children=item.num_children,
                            num_infants=item.num_infants,
                            num_youth=item.num_youth,
                            num_student_eu=item.num_student_eu,
                            item_price=item_price,
                        )
                    )
                    item.time_slot.available_adults -= item.num_adults
                    item.time_slot.available_children -= item.num_children
                    item.time_slot.available_infants -= item.num_infants
                    item.time_slot.available_student_eu -= item.num_student_eu
                    item.time_slot.available_youth -= item.num_youth
                    item.time_slot.save()

                BookingItem.objects.bulk_create(order_items_to_create)
                cartitems.delete()
                booking.total_price = total_price
                booking.save()
            else:
                booking_item = BookingItem.objects.create(
                    booking=booking, **single_item
                )
                booking.total_price = booking_item.item_price
                booking.save()
                booking_item.time_slot.available_adults -= booking_item.num_adults
                booking_item.time_slot.available_children -= booking_item.num_children
                booking_item.time_slot.available_infants -= booking_item.num_infants
                booking_item.time_slot.available_student_eu -= (
                    booking_item.num_student_eu
                )
                booking_item.time_slot.available_youth -= booking_item.num_youth
                booking_item.time_slot.save()

            # Send the notification only after the transaction commits
            transaction.on_commit(lambda: send_booking_notification(booking.id))
            return booking


class BookingItemSerializerForBookinDetails(serializers.ModelSerializer):
    time_slot = TimeSlotSerializer(read_only=True)
    tour_plan = TourPlanSerializer(read_only=True)

    class Meta:
        model = BookingItem
        fields = "__all__"
        read_only_fields = ["id", "booking", "tour_plan", "time_slot"]


class BookingDetailsSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    full_name = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(required=False, max_length=254)
    whatsapp = PhoneNumberField(required=False)
    country = serializers.CharField(write_only=True, required=False)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    book_now = serializers.BooleanField(write_only=True, required=False)
    single_item = BookingItemCreateSerializer(write_only=True, required=False)

    class Meta:
        model = Booking
        fields = "__all__"
        read_only_fields = ["id", "user", "total_price"]

    def get_items(self, object):
        items = BookingItem.objects.filter(booking=object)
        return BookingItemSerializerForBookinDetails(
            items, many=True, context=self.context
        ).data

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        status = attrs.get("status")
        cancelled_reason = attrs.get("cancelled_reason")

        if status == "cancelled" and (
            not cancelled_reason or len(cancelled_reason) <= 0
        ):
            raise serializers.ValidationError(
                {
                    "cancelled_reason": "Cancelled reason is required when status is cancelled."
                }
            )

        return attrs
