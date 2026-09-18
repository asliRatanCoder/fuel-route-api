import numpy as np
from django.test import SimpleTestCase

from routing.services import polyline
from routing.tests.helpers import encode_polyline


class PolylineDecodeTests(SimpleTestCase):
    def test_reference_example_from_the_format_specification(self):
        latitudes, longitudes = polyline.decode('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
        np.testing.assert_allclose(latitudes, [38.5, 40.7, 43.252])
        np.testing.assert_allclose(longitudes, [-120.2, -120.95, -126.453])

    def test_empty_string(self):
        latitudes, longitudes = polyline.decode('')
        self.assertEqual(len(latitudes), 0)
        self.assertEqual(len(longitudes), 0)

    def test_round_trip_of_a_long_random_line(self):
        rng = np.random.default_rng(7)
        latitudes = 25 + np.cumsum(rng.normal(0, 0.01, 5000))
        longitudes = -120 + np.cumsum(rng.normal(0, 0.01, 5000))
        decoded = polyline.decode(encode_polyline(latitudes, longitudes))
        np.testing.assert_allclose(decoded[0], latitudes, atol=1e-5)
        np.testing.assert_allclose(decoded[1], longitudes, atol=1e-5)
