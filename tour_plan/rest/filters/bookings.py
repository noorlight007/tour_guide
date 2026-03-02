import django_filters

from tour_plan.models import Booking


class BookingFilter(django_filters.FilterSet):
    id = django_filters.CharFilter(field_name="id", lookup_expr="icontains")
    created_at_from = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at_to = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Booking
        fields = ["status", "id", "created_at_from", "created_at_to"]
