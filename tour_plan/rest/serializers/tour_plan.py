from rest_framework import serializers

from tour_plan.models import Image, Location, TourPlan
from tour_plan.rest.serializers.image import ImageSerializer
from tour_plan.rest.serializers.location import LocationSerializer


class TourPlanSerializer(serializers.ModelSerializer):
    locations = LocationSerializer(many=True, read_only=True)
    images = ImageSerializer(many=True, read_only=True)
    image_ids = serializers.PrimaryKeyRelatedField(
        queryset=Image.objects.all(), many=True, write_only=True, source="images"
    )
    location_ids = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), many=True, write_only=True, source="locations"
    )
    max_adults = serializers.CharField(required=False, write_only=True)
    max_children = serializers.CharField(required=False, write_only=True)
    max_infants = serializers.CharField(required=False, write_only=True)
    max_student_eu = serializers.CharField(required=False, write_only=True)
    max_youth = serializers.CharField(required=False, write_only=True)

    class Meta:
        model = TourPlan
        fields = "__all__"

    def create(self, validated_data):
        validated_data.pop("max_adults")
        validated_data.pop("max_children")
        validated_data.pop("max_infants")
        validated_data.pop("max_student_eu")
        validated_data.pop("max_youth")
        return super().create(validated_data)
