"""
Client for the OSRM routing API (https://project-osrm.org). The public demo
server is free and needs no API key; any self-hosted OSRM works too via the
``OSRM_BASE_URL`` setting.

Planning a trip costs exactly ONE request to this API.
"""

import logging
from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

from routing.exceptions import NoRouteFound, UpstreamServiceError
from routing.services import polyline
from routing.services.geo import METERS_PER_MILE

logger = logging.getLogger(__name__)

# One shared session keeps the TLS connection to the router alive between
# requests, which saves a few hundred milliseconds per call.
_session = requests.Session()


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_seconds: float
    latitudes: np.ndarray
    longitudes: np.ndarray


def fetch_route(start, finish):
    """Driving route between two ``(latitude, longitude)`` pairs."""
    coordinates = f'{start[1]:.6f},{start[0]:.6f};{finish[1]:.6f},{finish[0]:.6f}'
    url = f'{settings.OSRM_BASE_URL}/route/v1/driving/{coordinates}'
    params = {'overview': 'full', 'geometries': 'polyline', 'steps': 'false'}

    try:
        response = _session.get(
            url,
            params=params,
            timeout=settings.EXTERNAL_API_TIMEOUT,
            headers={'User-Agent': settings.EXTERNAL_API_USER_AGENT},
        )
    except requests.RequestException as exc:
        logger.warning('OSRM request failed: %s', exc)
        raise UpstreamServiceError('The routing service could not be reached.') from exc

    # OSRM reports "no route" as HTTP 400 with a JSON body, so parse first.
    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamServiceError(
            f'The routing service answered with HTTP {response.status_code}.'
        ) from exc

    code = payload.get('code')
    if code in {'NoRoute', 'NoSegment'}:
        raise NoRouteFound('No drivable route exists between these two locations.')
    if code != 'Ok' or not payload.get('routes'):
        raise UpstreamServiceError(f'The routing service answered with "{code}".')

    route = payload['routes'][0]
    latitudes, longitudes = polyline.decode(route['geometry'])
    return Route(
        distance_miles=route['distance'] / METERS_PER_MILE,
        duration_seconds=route['duration'],
        latitudes=latitudes,
        longitudes=longitudes,
    )
