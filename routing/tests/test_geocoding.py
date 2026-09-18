from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from routing.exceptions import LocationNotFound, LocationOutsideUSA, UpstreamServiceError
from routing.models import Place
from routing.services import geocoding
from routing.services.gazetteer import compact_key, normalize_name, place_key
from routing.tests.helpers import FakeResponse


def make_place(name, state, latitude, longitude, population=1000):
    return Place.objects.create(
        key=place_key(name, state), compact_key=compact_key(name, state),
        name=name, state=state, latitude=latitude, longitude=longitude, population=population,
    )


class NormalisationTests(SimpleTestCase):
    def test_spelling_variants_share_a_key(self):
        self.assertEqual(normalize_name('St. Louis'), normalize_name('SAINT  LOUIS'))
        self.assertEqual(normalize_name("Coeur d'Alene"), 'coeur dalene')
        self.assertEqual(compact_key('Mc Calla', 'al'), compact_key('McCalla', 'AL'))

    def test_split_city_state(self):
        cases = {
            'Dallas, TX': ('Dallas', 'TX'),
            'dallas tx': ('dallas', 'TX'),
            'Salt Lake City, Utah': ('Salt Lake City', 'UT'),
            'Chicago, IL 60601, USA': ('Chicago', 'IL'),
            'New York, New York': ('New York', 'NY'),
            'Chicago': None,
            '350 5th Ave, New York, NY': None,
            'Paris, France': None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(geocoding.split_city_state(text), expected)


class ResolveTests(TestCase):
    def setUp(self):
        cache.clear()
        make_place('New York City', 'NY', 40.71427, -74.00597, 8_800_000)
        make_place('McCalla', 'AL', 33.34872, -87.01360)

    def test_coordinates_need_no_lookup(self):
        location = geocoding.resolve(' 34.0522, -118.2437 ')
        self.assertEqual(location.point, (34.0522, -118.2437))
        self.assertEqual((location.source, location.api_calls), ('coordinates', 0))

    def test_coordinates_outside_the_usa_are_rejected(self):
        with self.assertRaises(LocationOutsideUSA):
            geocoding.resolve('51.5074,-0.1278')

    def test_city_state_is_answered_locally(self):
        with mock.patch.object(geocoding._session, 'get') as http_get:
            for text in ('New York, NY', 'new york city, new york', 'Mc Calla, AL'):
                with self.subTest(text=text):
                    location = geocoding.resolve(text)
                    self.assertEqual((location.source, location.api_calls), ('gazetteer', 0))
        http_get.assert_not_called()

    def test_addresses_fall_back_to_nominatim_once_then_cache(self):
        hit = [{'lat': '38.8977', 'lon': '-77.0365', 'display_name': 'White House, Washington, DC'}]
        with mock.patch.object(geocoding._session, 'get', return_value=FakeResponse(hit)) as http_get:
            first = geocoding.resolve('1600 Pennsylvania Ave NW, Washington, DC')
            second = geocoding.resolve('1600 pennsylvania ave nw, washington, dc')
        self.assertEqual((first.source, first.api_calls), ('nominatim', 1))
        self.assertEqual(second.api_calls, 0)
        self.assertEqual(http_get.call_count, 1)
        self.assertEqual(http_get.call_args.kwargs['params']['countrycodes'], 'us')

    def test_unknown_place(self):
        with mock.patch.object(geocoding._session, 'get', return_value=FakeResponse([])):
            with self.assertRaises(LocationNotFound):
                geocoding.resolve('Nowhereville, ZZ')

    def test_geocoder_outage(self):
        with mock.patch.object(geocoding._session, 'get', return_value=FakeResponse({}, 503)):
            with self.assertLogs('routing', level='WARNING'), self.assertRaises(UpstreamServiceError):
                geocoding.resolve('Some Unknown Address 123')
