from urllib.parse import urlencode

from django.urls import reverse
from django.views.generic import TemplateView
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler

from routing.exceptions import RoutePlanningError
from routing.serializers import RoutePlanRequestSerializer
from routing.services.planner import plan_trip


class RoutePlanView(APIView):
    """
    GET  /api/route/?start=New York, NY&finish=Los Angeles, CA
    POST /api/route/   {"start": "New York, NY", "finish": "Los Angeles, CA"}

    Returns the route, the cheapest places to refuel along it, and the total
    fuel cost. See the README for the full response shape.
    """

    def get(self, request):
        return self.plan(request, request.query_params)

    def post(self, request):
        return self.plan(request, request.data)

    def plan(self, request, data):
        serializer = RoutePlanRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        plan = plan_trip(
            params['start'],
            params['finish'],
            initial_gallons=params['initial_fuel_gallons'],
            stop_penalty=params['stop_penalty'],
        )

        # Link to the interactive map of this exact plan (served from cache).
        query = {key: value for key, value in serializer.initial_data.items() if key in params}
        plan['map']['url'] = request.build_absolute_uri(f"{reverse('map')}?{urlencode(query)}")
        return Response(plan)


class MapView(TemplateView):
    """Single-page Leaflet map that calls the JSON API and draws the plan."""
    template_name = 'routing/map.html'


def api_exception_handler(exc, context):
    """One error envelope for everything: {"error": {"code", "message", ...}}."""
    if isinstance(exc, RoutePlanningError):
        return Response(
            {'error': {'code': exc.code, 'message': exc.message}}, status=exc.status_code
        )
    response = exception_handler(exc, context)
    if response is not None:
        error = {'code': 'invalid_request' if isinstance(exc, ValidationError) else 'error'}
        if isinstance(exc, ValidationError):
            error['message'] = 'Invalid request parameters.'
            error['fields'] = response.data
        else:
            error['message'] = response.data.get('detail', str(exc))
        response.data = {'error': error}
    return response
