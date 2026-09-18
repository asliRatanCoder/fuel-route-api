from django.urls import path

from routing.views import MapView, RoutePlanView

urlpatterns = [
    path('', MapView.as_view(), name='map'),
    path('api/route/', RoutePlanView.as_view(), name='route-plan'),
]
