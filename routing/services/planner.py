"""
Orchestrates a trip plan:

    geocode start/finish  ->  ONE routing API call  ->  stations along the
    route (in-memory KD-tree)  ->  cheapest purchases (DP)  ->  response

Routes and finished plans are cached, so repeating a request - or opening the
HTML map for a plan that was just computed - costs no external call at all.
"""

import math
import time

import numpy as np
from django.conf import settings
from django.core.cache import cache

from routing.exceptions import NoFeasibleFuelPlan
from routing.services import geocoding, osrm
from routing.services.optimizer import Infeasible, plan_purchases
from routing.services.stations import get_station_index, resample_route


def plan_trip(start_text, finish_text, *, initial_gallons=None, stop_penalty=None):
    started = time.perf_counter()
    if initial_gallons is None:  # the vehicle leaves with a full tank
        initial_gallons = settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG
    if stop_penalty is None:
        stop_penalty = settings.FUEL_STOP_PENALTY_USD

    start = geocoding.resolve(start_text)
    finish = geocoding.resolve(finish_text)
    calls = {'routing': 0, 'geocoding': start.api_calls + finish.api_calls}

    route_key = 'route:{:.4f},{:.4f}:{:.4f},{:.4f}'.format(*start.point, *finish.point)
    plan_key = f'plan:{route_key}:{initial_gallons:.2f}:{stop_penalty:.2f}'

    plan = cache.get(plan_key)
    cached = plan is not None
    if not cached:
        route = cache.get(route_key)
        if route is None:
            route = osrm.fetch_route(start.point, finish.point)
            calls['routing'] = 1
            cache.set(route_key, route)
        plan = _build_plan(route, initial_gallons, stop_penalty)
        cache.set(plan_key, plan)

    return {
        'start': _describe(start_text, start),
        'finish': _describe(finish_text, finish),
        **plan,
        'meta': {
            'external_api_calls': calls,
            'served_from_cache': cached,
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
        },
    }


def _describe(query, location):
    return {
        'query': query,
        'resolved_as': location.label,
        'latitude': round(location.latitude, 5),
        'longitude': round(location.longitude, 5),
        'geocoder': location.source,
    }


def _build_plan(route, initial_gallons, stop_penalty):
    index = get_station_index()
    nearby = index.along(resample_route(route), settings.ROUTE_CORRIDOR_MILES)

    try:
        purchases = plan_purchases(
            nearby.route_miles,
            index.prices[nearby.indices],
            route.distance_miles,
            range_miles=settings.VEHICLE_RANGE_MILES,
            mpg=settings.VEHICLE_MPG,
            initial_gallons=initial_gallons,
            stop_penalty=stop_penalty,
        )
    except Infeasible as gap:
        raise NoFeasibleFuelPlan(
            f'The fuel price list has no station within {settings.ROUTE_CORRIDOR_MILES:g} miles '
            f'of this route between mile {gap.from_mile:.0f} and mile {gap.to_mile:.0f} '
            f'(of {route.distance_miles:.0f}), which is further than the vehicle can drive on '
            f'the fuel it would have ({initial_gallons:g} gal at departure, '
            f'{settings.VEHICLE_RANGE_MILES:g}-mile maximum range).'
        ) from gap

    stops = []
    for number, purchase in enumerate(purchases, start=1):
        station = index.stations[nearby.indices[purchase.station]]
        stops.append({
            'stop': number,
            'opis_id': station['opis_id'],
            'name': station['name'],
            'address': station['address'],
            'city': station['city'],
            'state': station['state'],
            'latitude': station['latitude'],
            'longitude': station['longitude'],
            'route_mile': round(float(nearby.route_miles[purchase.station]), 1),
            'miles_off_route': round(float(nearby.offset_miles[purchase.station]), 1),
            'price_per_gallon': round(float(station['price']), 3),
            'fuel_on_arrival_gallons': round(purchase.arrival_gallons, 2),
            'gallons_purchased': round(purchase.gallons, 2),
            'cost': round(purchase.cost, 2),
        })

    notes = []
    if not stops:
        notes.append('The fuel on board at departure covers the whole trip; no stop is needed.')

    gallons = sum(p.gallons for p in purchases)
    total_cost = sum(p.cost for p in purchases)
    return {
        'route': {
            'distance_miles': round(route.distance_miles, 1),
            'duration_hours': round(route.duration_seconds / 3600, 2),
        },
        'vehicle': {
            'range_miles': settings.VEHICLE_RANGE_MILES,
            'miles_per_gallon': settings.VEHICLE_MPG,
            'tank_gallons': settings.VEHICLE_RANGE_MILES / settings.VEHICLE_MPG,
            'initial_fuel_gallons': initial_gallons,
        },
        'summary': {
            'total_fuel_cost': round(total_cost, 2),
            'total_gallons_purchased': round(gallons, 2),
            'fuel_used_gallons': round(route.distance_miles / settings.VEHICLE_MPG, 2),
            'average_price_per_gallon': round(total_cost / gallons, 3) if gallons else None,
            'number_of_stops': len(stops),
            'stations_considered': int(len(nearby.indices)),
        },
        'fuel_stops': stops,
        'notes': notes,
        'map': {'geojson': _feature_collection(route, stops)},
    }


def _feature_collection(route, stops):
    """The map: route line plus start, finish and fuel stops, as GeoJSON."""
    stride = max(1, math.ceil(len(route.latitudes) / settings.RESPONSE_GEOMETRY_MAX_POINTS))
    keep = np.arange(0, len(route.latitudes), stride)
    if keep[-1] != len(route.latitudes) - 1:
        keep = np.append(keep, len(route.latitudes) - 1)
    line = np.column_stack((route.longitudes[keep], route.latitudes[keep])).round(5).tolist()

    def point(longitude, latitude, **properties):
        return {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [longitude, latitude]},
            'properties': properties,
        }

    features = [
        {
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': line},
            'properties': {'kind': 'route'},
        },
        point(*line[0], kind='start'),
        point(*line[-1], kind='finish'),
    ]
    features += [
        point(
            stop['longitude'], stop['latitude'], kind='fuel_stop', stop=stop['stop'],
            name=stop['name'], price_per_gallon=stop['price_per_gallon'],
            gallons_purchased=stop['gallons_purchased'], cost=stop['cost'],
        )
        for stop in stops
    ]
    return {'type': 'FeatureCollection', 'features': features}
