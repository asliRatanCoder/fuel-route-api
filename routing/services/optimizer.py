"""
Where to buy fuel, and how much.

Given the stations passed along a route (trip mile + price), find the purchases
that minimise

    total fuel cost  +  stop_penalty x number of stops

subject to never running dry and never exceeding the tank.

Why a penalty? Minimising fuel cost alone has a well-known greedy solution,
but on real price data it chases every one-cent improvement and happily plans
twenty 3-gallon stops. A small fixed cost per stop (the driver's time) makes
the plan one a person would actually drive. With ``stop_penalty=0`` the result
is the pure minimum fuel cost.

Method: dynamic programming over (station, fuel in tank). The trip is cut into
N equal steps of roughly one mile; ``cost[f]`` is the cheapest way to be at the
current station with ``f`` steps' worth of fuel on board. Two transitions:

* drive to the next station -> shift the array by the distance;
* buy ``f' - f`` steps of fuel  -> ``cost[f'] = min_f(cost[f] - f*c) + f'*c + penalty``,
  which is a running minimum, so each station costs O(tank) numpy work
  instead of O(tank^2).

Pure numpy, no Django imports: easy to test in isolation.
"""

import math
from dataclasses import dataclass

import numpy as np


class Infeasible(Exception):
    """No plan exists: the stretch ``from_mile``..``to_mile`` exceeds the range in hand."""

    def __init__(self, from_mile, to_mile):
        super().__init__(f'no reachable fuel between mile {from_mile:.0f} and mile {to_mile:.0f}')
        self.from_mile = from_mile
        self.to_mile = to_mile


@dataclass(frozen=True)
class Purchase:
    station: int            # position in the arrays handed to ``plan_purchases``
    gallons: float
    cost: float             # USD
    arrival_gallons: float  # fuel left in the tank when pulling in


def plan_purchases(station_miles, prices, trip_miles, *, range_miles, mpg,
                   initial_gallons=0.0, stop_penalty=0.0):
    """
    ``station_miles`` and ``prices`` (USD/gallon) describe the stations along
    the route. Returns the purchases in driving order, or raises ``Infeasible``.
    """
    station_miles = np.asarray(station_miles, dtype=float)
    prices = np.asarray(prices, dtype=float)
    if trip_miles <= 0:
        return []

    # Grid: N equal steps that add up to the trip exactly, so gallons and
    # dollars come out exact; stations snap to the nearest step (< 0.5 mi).
    steps = max(1, math.ceil(trip_miles))
    step_miles = trip_miles / steps
    tank = int(range_miles / step_miles + 1e-9)
    fuel = min(tank, int(initial_gallons * mpg / step_miles + 1e-9))

    # One candidate per grid position (the cheapest); a station at the very
    # end of the trip is useless.
    position = np.rint(station_miles / step_miles).astype(int)
    order = np.lexsort((prices, position))
    order = order[position[order] < steps]
    first_at_position = np.ones(len(order), dtype=bool)
    first_at_position[1:] = position[order][1:] != position[order][:-1]
    candidates = order[first_at_position]
    position = position[candidates]
    step_price = prices[candidates] * step_miles / mpg

    levels = np.arange(tank + 1)
    cost = np.full(tank + 1, np.inf)
    cost[fuel] = 0.0
    fuel_before = np.empty((len(candidates), tank + 1), dtype=np.int32)

    here = 0
    for k, (there, price) in enumerate(zip(position.tolist(), step_price.tolist())):
        cost = _drive(cost, there - here, here * step_miles, there * step_miles)
        here = there

        # Buying up to level f' from the best lower level f < f'.
        base = cost - price * levels
        best = np.minimum.accumulate(base)
        best_level = np.maximum.accumulate(np.where(base <= best, levels, 0))
        buy = np.full(tank + 1, np.inf)
        buy[1:] = best[:-1] + price * levels[1:] + stop_penalty

        bought = buy < cost
        fuel_before[k] = levels
        fuel_before[k, 1:][bought[1:]] = best_level[:-1][bought[1:]]
        cost = np.where(bought, buy, cost)

    cost = _drive(cost, steps - here, here * step_miles, trip_miles)
    level = int(np.argmin(cost))  # fuel left at the destination

    # Walk back through the decisions.
    purchases = []
    level += steps - here
    for k in range(len(candidates) - 1, -1, -1):
        before = int(fuel_before[k, level])
        if before != level:
            gallons = (level - before) * step_miles / mpg
            purchases.append(Purchase(
                station=int(candidates[k]),
                gallons=gallons,
                cost=gallons * float(prices[candidates[k]]),
                arrival_gallons=before * step_miles / mpg,
            ))
        previous = int(position[k - 1]) if k else 0
        level = before + int(position[k]) - previous
    purchases.reverse()
    return purchases


def _drive(cost, distance, from_mile, to_mile):
    """Burn ``distance`` steps of fuel: level f becomes f - distance."""
    if distance == 0:
        return cost
    moved = np.full_like(cost, np.inf)
    if distance < len(cost):
        moved[:-distance] = cost[distance:]
    if not np.isfinite(moved).any():
        raise Infeasible(from_mile, to_mile)
    return moved
