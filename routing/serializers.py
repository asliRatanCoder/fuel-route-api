from django.conf import settings
from rest_framework import serializers


class RoutePlanRequestSerializer(serializers.Serializer):
    """Validates the query string (GET) or JSON body (POST) of a plan request."""

    start = serializers.CharField(
        max_length=200, help_text='"City, ST", a street address, or "lat,lng".'
    )
    finish = serializers.CharField(max_length=200)
    initial_fuel_gallons = serializers.FloatField(
        required=False, default=None, min_value=0.0,
        help_text='Fuel in the tank at departure. Defaults to a full tank.',
    )
    stop_penalty = serializers.FloatField(
        required=False, default=None, min_value=0.0, max_value=100.0,
        help_text='USD "cost" of making a stop, used only to avoid tiny top-ups. 0 = pure min cost.',
    )

    def validate_initial_fuel_gallons(self, value):
        tank = settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG
        if value is not None and value > tank:
            raise serializers.ValidationError(f'The tank only holds {tank:g} gallons.')
        return value
