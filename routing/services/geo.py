"""Small vectorised geodesy helpers (numpy)."""

import numpy as np

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344

# Rough bounding boxes (south, west, north, east) for a cheap "is this in the
# USA?" check on raw coordinates: the lower 48, Alaska and Hawaii.
_US_BOUNDS = (
    (24.4, -125.0, 49.5, -66.9),
    (51.0, -180.0, 71.5, -129.9),
    (18.8, -160.4, 22.4, -154.7),
)


def in_usa(latitude, longitude):
    return any(
        south <= latitude <= north and west <= longitude <= east
        for south, west, north, east in _US_BOUNDS
    )


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles; accepts scalars or numpy arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def to_cartesian_miles(latitudes, longitudes):
    """
    Project points onto a sphere measured in miles. Straight-line (chord)
    distance between such points is, for the few miles we care about,
    indistinguishable from the distance along the surface, which lets a plain
    KD-tree answer "how far is this station from the route?".
    """
    lat, lon = np.radians(latitudes), np.radians(longitudes)
    cos_lat = np.cos(lat)
    return EARTH_RADIUS_MILES * np.column_stack(
        (cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat))
    )
