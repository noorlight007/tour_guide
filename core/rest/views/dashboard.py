from decimal import Decimal

from django.db.models import Sum
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from tour_plan.models import Booking, BookingItem, Contact


class DashboardAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        total_bookings = Booking.objects.count()
        completed_bookings = Booking.objects.filter(status="completed").count()
        completion_rate = (
            round((completed_bookings / total_bookings) * 100, 2)
            if total_bookings > 0
            else 0
        )
        total_income = BookingItem.objects.filter(
            booking__status="completed"
        ).aggregate(total=Sum("item_price"))["total"] or Decimal("0.00")
        total_client_request = Contact.objects.count()

        return Response(
            {
                "total_bookings": total_bookings,
                "completed_bookings": completed_bookings,
                "completion_rate": f"{completion_rate}%",
                "total_income": total_income,
                "total_client_request": total_client_request,
            }
        )
