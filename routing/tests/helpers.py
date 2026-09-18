"""Test helpers: fabricate what the OSRM API would return for a given line."""

import numpy as np

from routing.services.geo import METERS_PER_MILE, haversine_miles


def encode_polyline(latitudes, longitudes, precision=5):
    scale = 10 ** precision
    points = np.column_stack((
        np.round(np.asarray(latitudes) * scale), np.round(np.asarray(longitudes) * scale),
    )).astype(np.int64)
    deltas = np.diff(points, axis=0, prepend=np.zeros((1, 2), dtype=np.int64)).ravel()

    output = []
    for delta in deltas.tolist():
        value = ~(delta << 1) if delta < 0 else delta << 1
        while value >= 0x20:
            output.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        output.append(chr(value + 63))
    return ''.join(output)


def line_length_miles(latitudes, longitudes):
    latitudes, longitudes = np.asarray(latitudes), np.asarray(longitudes)
    return float(haversine_miles(
        latitudes[:-1], longitudes[:-1], latitudes[1:], longitudes[1:]
    ).sum())


def osrm_payload(latitudes, longitudes, duration_seconds=3600.0):
    return {
        'code': 'Ok',
        'routes': [{
            'distance': line_length_miles(latitudes, longitudes) * METERS_PER_MILE,
            'duration': duration_seconds,
            'geometry': encode_polyline(latitudes, longitudes),
        }],
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f'HTTP {self.status_code}')
