"""
In-memory index of every fuel station, and the query that matters: which
stations lie along a route, and at what mile of the trip?

The station table is small (~6.6k rows) and static, so it is read from the
database once per process into numpy arrays. Matching a coast-to-coast route
against it then takes a few milliseconds.
"""

import threading
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from routing.models import FuelStation
from routing.services.geo import haversine_miles, to_cartesian_miles

# The route line is re-sampled to one point per this many miles before the
# nearest-point search. OSRM geometry is sparse on long straight roads, so
# measuring to its raw vertices would miss stations sitting mid-segment.
RESAMPLE_STEP_MILES = 0.5
MILES_PER_DEGREE_LATITUDE = 69.0


@dataclass(frozen=True)
class RouteLine:
    """A route re-sampled at even spacing; ``miles[i]`` is the trip mile of point i."""
    miles: np.ndarray
    latitudes: np.ndarray
    longitudes: np.ndarray


@dataclass(frozen=True)
class StationsAlongRoute:
    indices: np.ndarray        # rows of the StationIndex
    route_miles: np.ndarray    # trip mile at which each station is passed
    offset_miles: np.ndarray   # how far each station sits from the route line


def resample_route(route):
    """Evenly spaced points along the route, scaled to OSRM's reported length."""
    lat, lon = route.latitudes, route.longitudes
    steps = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    moving = np.concatenate(([True], steps > 0))  # np.interp needs increasing x
    lat, lon = lat[moving], lon[moving]
    along = np.concatenate(([0.0], np.cumsum(steps[steps > 0])))

    length = along[-1] if len(along) else 0.0
    if length == 0.0:
        return RouteLine(np.zeros(1), lat[:1], lon[:1])

    samples = np.append(np.arange(0.0, length, RESAMPLE_STEP_MILES), length)
    return RouteLine(
        miles=samples * (route.distance_miles / length),
        latitudes=np.interp(samples, along, lat),
        longitudes=np.interp(samples, along, lon),
    )


class StationIndex:
    def __init__(self, stations):
        self.stations = stations  # list of dicts, row i <-> array position i
        self.latitudes = np.array([s['latitude'] for s in stations], dtype=float)
        self.longitudes = np.array([s['longitude'] for s in stations], dtype=float)
        self.prices = np.array([float(s['price']) for s in stations], dtype=float)
        self._cartesian = to_cartesian_miles(self.latitudes, self.longitudes)

    def __len__(self):
        return len(self.stations)

    @classmethod
    def from_database(cls):
        return cls(list(FuelStation.objects.order_by('opis_id').values(
            'opis_id', 'name', 'address', 'city', 'state', 'price', 'latitude', 'longitude',
        )))

    def along(self, line, corridor_miles):
        """Stations within ``corridor_miles`` of the route, ordered by trip mile."""
        # Cheap bounding-box cut first, so the tree is only asked about
        # stations that could possibly qualify.
        lat_pad = corridor_miles / MILES_PER_DEGREE_LATITUDE
        widest_latitude = np.radians(min(np.abs(line.latitudes).max() + lat_pad, 89.0))
        lon_pad = lat_pad / np.cos(widest_latitude)
        nearby = np.flatnonzero(
            (self.latitudes >= line.latitudes.min() - lat_pad)
            & (self.latitudes <= line.latitudes.max() + lat_pad)
            & (self.longitudes >= line.longitudes.min() - lon_pad)
            & (self.longitudes <= line.longitudes.max() + lon_pad)
        )
        if nearby.size == 0:
            empty = np.empty(0)
            return StationsAlongRoute(nearby, empty, empty)

        tree = cKDTree(to_cartesian_miles(line.latitudes, line.longitudes))
        offsets, nearest = tree.query(self._cartesian[nearby], distance_upper_bound=corridor_miles)
        hit = np.isfinite(offsets)  # misses come back as inf

        indices, offsets, route_miles = nearby[hit], offsets[hit], line.miles[nearest[hit]]
        order = np.argsort(route_miles, kind='stable')
        return StationsAlongRoute(indices[order], route_miles[order], offsets[order])


_index = None
_index_lock = threading.Lock()


def get_station_index():
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = StationIndex.from_database()
    return _index


def reset_station_index():
    """Forget the cached index (used by tests and after reloading data)."""
    global _index
    _index = None
