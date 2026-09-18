from decimal import Decimal
from unittest import mock

import numpy as np
import requests
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from routing.models import FuelStation
from routing.services import osrm
from routing.services.stations import reset_station_index
from routing.tests.helpers import FakeResponse, line_length_miles, osrm_payload

# A fake ~1,060-mile route due east along the 40th parallel.
LONGITUDES = np.arange(-100.0, -79.95, 0.1)
LATITUDES = np.full_like(LONGITUDES, 40.0)
TRIP_MILES = line_length_miles(LATITUDES, LONGITUDES)
START, FINISH = '40.0,-100.0', '40.0,-80.0'


def add_station(opis_id, name, longitude, price, latitude=40.02):
    FuelStation.objects.create(
        opis_id=opis_id, name=name, address='I-80', city='Somewhere', state='NE',
        price=Decimal(price), latitude=latitude, longitude=longitude,
    )


class RoutePlanApiTests(TestCase):
    url = reverse('route-plan')

    def setUp(self):
        cache.clear()
        reset_station_index()
        add_station(1, 'Pricey', -95.0, '3.500')            # mile ~265
        add_station(2, 'Fair', -92.0, '3.000')              # mile ~424
        add_station(3, 'Cheap', -85.0, '2.500')             # mile ~796
        add_station(4, 'Cheapest but 140 miles away', -90.0, '1.000', latitude=42.0)
        self.router = mock.patch.object(
            osrm._session, 'get', return_value=FakeResponse(osrm_payload(LATITUDES, LONGITUDES)),
        ).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(reset_station_index)

    def test_plans_the_cheapest_stops_with_a_single_routing_call(self):
        response = self.client.get(self.url, {'start': START, 'finish': FINISH})
        self.assertEqual(response.status_code, 200)
        plan = response.json()

        self.assertEqual([stop['name'] for stop in plan['fuel_stops']], ['Fair', 'Cheap'])
        fair, cheap = plan['fuel_stops']
        self.assertAlmostEqual(plan['route']['distance_miles'], TRIP_MILES, delta=0.1)
        # Leaves full, buys at "Fair" only what it takes to reach "Cheap",
        # then at "Cheap" only what it takes to finish.
        self.assertAlmostEqual(fair['gallons_purchased'], (cheap['route_mile'] - 500) / 10, delta=0.2)
        self.assertAlmostEqual(cheap['fuel_on_arrival_gallons'], 0, delta=0.1)
        self.assertAlmostEqual(
            plan['summary']['total_gallons_purchased'], (TRIP_MILES - 500) / 10, delta=0.05
        )
        self.assertAlmostEqual(
            plan['summary']['total_fuel_cost'],
            fair['gallons_purchased'] * 3.0 + cheap['gallons_purchased'] * 2.5, delta=0.05,
        )

        self.assertEqual(plan['meta']['external_api_calls'], {'routing': 1, 'geocoding': 0})
        self.assertEqual(self.router.call_count, 1)

        kinds = [f['properties']['kind'] for f in plan['map']['geojson']['features']]
        self.assertEqual(kinds, ['route', 'start', 'finish', 'fuel_stop', 'fuel_stop'])
        self.assertIn('start=40.0%2C-100.0', plan['map']['url'])

    def test_repeat_requests_are_served_from_cache(self):
        self.client.get(self.url, {'start': START, 'finish': FINISH})
        again = self.client.get(self.url, {'start': START, 'finish': FINISH}).json()
        self.assertTrue(again['meta']['served_from_cache'])
        self.assertEqual(again['meta']['external_api_calls']['routing'], 0)
        # Different fuel assumptions reuse the cached route, not the cached plan.
        other = self.client.get(
            self.url, {'start': START, 'finish': FINISH, 'initial_fuel_gallons': 30}
        ).json()
        self.assertFalse(other['meta']['served_from_cache'])
        self.assertEqual(other['fuel_stops'][0]['name'], 'Pricey')
        self.assertEqual(self.router.call_count, 1)

    def test_post_json_body(self):
        response = self.client.post(
            self.url, {'start': START, 'finish': FINISH}, content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['summary']['number_of_stops'], 2)

    def test_short_trip_needs_no_fuel(self):
        self.router.return_value = FakeResponse(osrm_payload(LATITUDES[:30], LONGITUDES[:30]))
        plan = self.client.get(self.url, {'start': START, 'finish': '40.0,-97.1'}).json()
        self.assertEqual(plan['fuel_stops'], [])
        self.assertEqual(plan['summary']['total_fuel_cost'], 0)
        self.assertTrue(plan['notes'])

    def test_validation_errors(self):
        cases = [
            ({'start': START}, 'finish'),
            ({'start': START, 'finish': FINISH, 'initial_fuel_gallons': 51}, 'initial_fuel_gallons'),
            ({'start': START, 'finish': FINISH, 'stop_penalty': -1}, 'stop_penalty'),
        ]
        for params, field in cases:
            with self.subTest(field=field):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'invalid_request')
                self.assertIn(field, response.json()['error']['fields'])
        self.router.assert_not_called()

    def test_location_outside_the_usa(self):
        response = self.client.get(self.url, {'start': '48.8566,2.3522', 'finish': FINISH})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'location_outside_usa')

    def test_no_drivable_route(self):
        self.router.return_value = FakeResponse({'code': 'NoRoute'}, 400)
        response = self.client.get(self.url, {'start': START, 'finish': FINISH})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'no_route')

    def test_stretch_without_fuel(self):
        FuelStation.objects.filter(opis_id__in=[1, 2]).delete()
        response = self.client.get(self.url, {'start': START, 'finish': FINISH})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error']['code'], 'no_feasible_fuel_plan')

    def test_routing_service_down(self):
        self.router.side_effect = requests.ConnectionError('boom')
        with self.assertLogs('routing', level='WARNING'):
            response = self.client.get(self.url, {'start': START, 'finish': FINISH})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'upstream_unavailable')

    def test_map_page_renders(self):
        response = self.client.get(reverse('map'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="map"')
