"""
Encoded polyline decoding (the Google algorithm used by OSRM).

A coast-to-coast route is ~30k points. Decoding that byte by byte in Python
takes tens of milliseconds; doing it with numpy array operations takes about
one, so the decoder below is fully vectorised.
"""

import numpy as np


def decode(encoded, precision=5):
    """Decode a polyline string into ``(latitudes, longitudes)`` float arrays."""
    if not encoded:
        return np.empty(0), np.empty(0)

    chunks = np.frombuffer(encoded.encode('ascii'), dtype=np.uint8).astype(np.int64) - 63
    # Each number is a run of 5-bit chunks, least significant first; a chunk
    # without the 0x20 continuation bit closes the run.
    ends = np.flatnonzero((chunks & 0x20) == 0)
    starts = np.concatenate(([0], ends[:-1] + 1))
    run_of_chunk = np.repeat(np.arange(len(ends)), ends - starts + 1)
    position_in_run = np.arange(len(chunks)) - starts[run_of_chunk]

    values = np.add.reduceat((chunks & 0x1F) << (5 * position_in_run), starts)
    deltas = np.where(values & 1, ~(values >> 1), values >> 1)  # zig-zag -> signed

    scale = 10.0 ** precision
    return np.cumsum(deltas[0::2]) / scale, np.cumsum(deltas[1::2]) / scale

