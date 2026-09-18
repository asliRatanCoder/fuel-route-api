import numpy as np
from django.test import SimpleTestCase

from routing.services.osrm import Route
from routing.services.stations import StationIndex, resample_route
from routing.tests.helpers import line_length_miles


def station(opis_id, latitude, longitude, price=3.0):
    return {
        'opis_id': opis_id, 'name': f'Station {opis_id}', 'address': '', 'city': '', 'state': '',
        'price': price, 'latitude': latitude, 'longitude': longitude,
    }


class StationsAlongRouteTests(SimpleTestCase):
    def setUp(self):
        # One ~530-mile straight segment described by just two vertices, the
        # way OSRM describes a long straight highway.
        latitudes, longitudes = np.array([40.0, 40.0]), np.array([-100.0, -90.0])
        self.length = line_length_miles(latitudes, longitudes)
        self.route = Route(self.length, 0.0, latitudes, longitudes)

    def test_resampling_is_dense_and_keeps_the_length(self):
        line = resample_route(self.route)
        self.assertLessEqual(np.diff(line.miles).max(), 0.51)
        self.assertAlmostEqual(line.miles[-1], self.length)
        self.assertAlmostEqual(line.longitudes[0], -100.0)
        self.assertAlmostEqual(line.longitudes[-1], -90.0)

    def test_finds_stations_mid_segment_and_ignores_distant_ones(self):
        index = StationIndex([
            station(1, 40.05, -92.0),    # ~3 miles north of the line, far from any vertex
            station(2, 41.00, -95.0),    # ~69 miles north: outside the corridor
            station(3, 39.95, -98.0),    # passed first
            station(4, 25.00, -80.0),    # Miami
        ])
        found = index.along(resample_route(self.route), corridor_miles=10)
        self.assertEqual([index.stations[i]['opis_id'] for i in found.indices], [3, 1])
        self.assertTrue(np.all(np.diff(found.route_miles) > 0))
        self.assertAlmostEqual(found.route_miles[0], self.length * 0.2, delta=2)
        self.assertAlmostEqual(found.offset_miles[1], 3.45, delta=0.3)

    def test_no_station_anywhere_near(self):
        index = StationIndex([station(4, 25.0, -80.0)])
        found = index.along(resample_route(self.route), corridor_miles=10)
        self.assertEqual(len(found.indices), 0)
