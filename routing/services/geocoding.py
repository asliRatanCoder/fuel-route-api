"""
Turn a user-supplied location into coordinates, spending an external API call
only as a last resort:

1. "lat,lng"                 -> used as is                        (0 API calls)
2. "City, ST" / "City, State" -> bundled GeoNames gazetteer (DB)   (0 API calls)
3. anything else (addresses)  -> Nominatim, cached                 (1 API call)
"""

import hashlib
import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from routing.exceptions import LocationNotFound, LocationOutsideUSA, UpstreamServiceError
from routing.models import Place
from routing.services.gazetteer import compact_key, parse_state, place_key
from routing.services.geo import in_usa

logger = logging.getLogger(__name__)

COORDINATES = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$')
COUNTRY_SUFFIXES = {'usa', 'us', 'u.s.', 'u.s.a.', 'united states', 'united states of america'}
ZIP_CODE = re.compile(r'\s+\d{5}(-\d{4})?$')
GEOCODE_CACHE_SECONDS = 24 * 60 * 60

_session = requests.Session()


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    label: str
    source: str  # 'coordinates' | 'gazetteer' | 'nominatim'
    api_calls: int = 0

    @property
    def point(self):
        return self.latitude, self.longitude


def resolve(text):
    """Resolve free text to a :class:`Location` inside the USA."""
    text = ' '.join(text.split())
    return _from_coordinates(text) or _from_gazetteer(text) or _from_nominatim(text)


def _from_coordinates(text):
    match = COORDINATES.match(text)
    if not match:
        return None
    latitude, longitude = float(match[1]), float(match[2])
    if not in_usa(latitude, longitude):
        raise LocationOutsideUSA(f'"{text}" is not inside the USA.')
    return Location(latitude, longitude, f'{latitude:.5f}, {longitude:.5f}', 'coordinates')


def split_city_state(text):
    """'Dallas, TX' / 'Dallas TX' / 'Dallas, Texas, USA' -> ('Dallas', 'TX'), else None."""
    parts = [part.strip() for part in text.split(',') if part.strip()]
    if parts and parts[-1].lower() in COUNTRY_SUFFIXES:
        parts.pop()
    if len(parts) == 1:  # no comma: "Dallas TX"
        city, _, tail = parts[0].rpartition(' ')
        parts = [city, tail]
    if len(parts) != 2 or not parts[0]:
        return None
    state = parse_state(ZIP_CODE.sub('', parts[1]))
    return (parts[0], state) if state else None


def _from_gazetteer(text):
    city_state = split_city_state(text)
    if city_state is None:
        return None
    city, state = city_state
    place = (
        Place.objects.filter(key=place_key(city, state)).first()
        or Place.objects.filter(compact_key=compact_key(city, state)).order_by('-population').first()
        # GeoNames files New York as "New York City".
        or Place.objects.filter(key=place_key(f'{city} city', state)).first()
    )
    if place is None:
        return None
    return Location(place.latitude, place.longitude, f'{place.name}, {place.state}', 'gazetteer')


def _from_nominatim(text):
    cache_key = 'geocode:' + hashlib.sha1(text.lower().encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _session.get(
            f'{settings.NOMINATIM_BASE_URL}/search',
            params={'q': text, 'format': 'jsonv2', 'limit': 1, 'countrycodes': 'us'},
            headers={'User-Agent': settings.EXTERNAL_API_USER_AGENT},
            timeout=settings.EXTERNAL_API_TIMEOUT,
        )
        response.raise_for_status()
        results = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Nominatim request failed: %s', exc)
        raise UpstreamServiceError('The geocoding service could not be reached.') from exc

    if not results:
        raise LocationNotFound(
            f'Could not find "{text}" in the USA. Try "City, ST" or "lat,lng".'
        )
    hit = results[0]
    location = Location(
        float(hit['lat']), float(hit['lon']), hit.get('display_name', text), 'nominatim',
    )
    # Cached copies cost no API call, so store it with the counter at zero.
    cache.set(cache_key, location, GEOCODE_CACHE_SECONDS)
    return Location(location.latitude, location.longitude, location.label, location.source, 1)
