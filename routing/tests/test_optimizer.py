import math
import random

from django.test import SimpleTestCase

from routing.services.optimizer import Infeasible, plan_purchases

VEHICLE = {'range_miles': 500, 'mpg': 10}


def reference_cost(miles, prices, trip, *, tank, mpg, initial, penalty):
    """
    Deliberately naive O(n * tank^2) version of the same optimisation, written
    with plain loops so it is obviously correct. Integer miles only.
    """
    cost = [math.inf] * (tank + 1)
    cost[initial] = 0.0
    here = 0
    for position, price in sorted(zip(miles, prices)):
        distance = position - here
        cost = [cost[f + distance] if f + distance <= tank else math.inf for f in range(tank + 1)]
        after = cost[:]
        for f in range(tank + 1):
            if cost[f] == math.inf:
                continue
            for bought in range(1, tank - f + 1):
                candidate = cost[f] + bought * price / mpg + penalty
                after[f + bought] = min(after[f + bought], candidate)
        cost, here = after, position
    remaining = trip - here
    return min(cost[remaining:], default=math.inf) if remaining <= tank else math.inf


class PlanPurchasesTests(SimpleTestCase):
    def test_buys_just_enough_to_reach_cheaper_fuel(self):
        # Full tank (500 mi). $4 at 250 is never worth it; at 450 buy only what
        # is needed to reach the $2 station at 900, then just enough to finish.
        purchases = plan_purchases(
            [250, 450, 900], [4.0, 3.0, 2.0], 1000, initial_gallons=50, **VEHICLE
        )
        self.assertEqual([p.station for p in purchases], [1, 2])
        self.assertAlmostEqual(purchases[0].arrival_gallons, 5.0)
        self.assertAlmostEqual(purchases[0].gallons, 40.0)
        self.assertAlmostEqual(purchases[1].arrival_gallons, 0.0)
        self.assertAlmostEqual(purchases[1].gallons, 10.0)
        self.assertAlmostEqual(sum(p.cost for p in purchases), 40 * 3.0 + 10 * 2.0)

    def test_fills_the_tank_when_everything_ahead_is_dearer(self):
        purchases = plan_purchases(
            [100, 400, 590], [2.0, 5.0, 5.0], 1000, initial_gallons=10, **VEHICLE
        )
        self.assertEqual(purchases[0].station, 0)
        self.assertAlmostEqual(purchases[0].gallons, 50.0)  # arrived empty, filled up

    def test_short_trip_needs_no_stop(self):
        self.assertEqual(plan_purchases([50], [3.0], 240, initial_gallons=50, **VEHICLE), [])

    def test_no_stations_at_all(self):
        self.assertEqual(plan_purchases([], [], 300, initial_gallons=50, **VEHICLE), [])
        with self.assertRaises(Infeasible):
            plan_purchases([], [], 800, initial_gallons=50, **VEHICLE)

    def test_gap_longer_than_the_range_is_reported(self):
        with self.assertRaises(Infeasible) as caught:
            plan_purchases([100, 700], [3.0, 3.0], 900, initial_gallons=50, **VEHICLE)
        self.assertAlmostEqual(caught.exception.from_mile, 100, delta=1)
        self.assertAlmostEqual(caught.exception.to_mile, 700, delta=1)

    def test_first_station_out_of_reach_of_the_starting_fuel(self):
        with self.assertRaises(Infeasible) as caught:
            plan_purchases([200], [3.0], 400, initial_gallons=5, **VEHICLE)
        self.assertEqual(caught.exception.from_mile, 0)

    def test_gallons_add_up_to_exactly_what_the_trip_burns(self):
        # 2793.4 miles is not a whole number of grid steps; totals must still be exact.
        miles = list(range(40, 2790, 35))
        prices = [3 + ((i * 37) % 50) / 100 for i in range(len(miles))]
        purchases = plan_purchases(miles, prices, 2793.4, initial_gallons=5, **VEHICLE)
        self.assertAlmostEqual(sum(p.gallons for p in purchases), (2793.4 - 50) / 10, places=1)

    def test_stop_penalty_trades_a_little_money_for_far_fewer_stops(self):
        # Prices fall by a cent every 25 miles: pure min-cost stops everywhere.
        miles = list(range(25, 2000, 25))
        prices = [4.0 - 0.01 * i for i in range(len(miles))]
        cheapest = plan_purchases(miles, prices, 2000, initial_gallons=50, stop_penalty=0, **VEHICLE)
        practical = plan_purchases(miles, prices, 2000, initial_gallons=50, stop_penalty=5, **VEHICLE)
        self.assertGreater(len(cheapest), 3 * len(practical))
        self.assertLessEqual(sum(p.cost for p in cheapest), sum(p.cost for p in practical))

    def test_plans_are_always_drivable(self):
        rng = random.Random(3)
        for _ in range(100):
            trip = rng.uniform(50, 3000)
            miles = sorted(rng.uniform(0, trip) for _ in range(rng.randint(5, 150)))
            prices = [rng.uniform(2.5, 4.5) for _ in miles]
            try:
                purchases = plan_purchases(
                    miles, prices, trip, initial_gallons=50, stop_penalty=rng.choice([0, 5]), **VEHICLE
                )
            except Infeasible:
                continue
            fuel, position = 50.0, 0.0
            for purchase in purchases:
                fuel -= (miles[purchase.station] - position) / 10
                position = miles[purchase.station]
                self.assertGreater(fuel, -0.06)          # never runs dry (0.5 mi grid slack)
                fuel += purchase.gallons
                self.assertLess(fuel, 50.06)             # never overfills
            self.assertGreater(fuel - (trip - position) / 10, -0.06)

    def test_matches_brute_force_on_random_instances(self):
        rng = random.Random(11)
        tank, mpg = 60, 10
        for case in range(300):
            trip = rng.randint(1, 260)
            miles = [rng.randint(0, trip) for _ in range(rng.randint(0, 12))]
            prices = [rng.choice([2.5, 2.75, 3.0, 3.1, 3.5, 4.0]) for _ in miles]
            initial = rng.randint(0, tank)
            penalty = rng.choice([0.0, 0.0, 0.4, 2.0])
            expected = reference_cost(
                miles, prices, trip, tank=tank, mpg=mpg, initial=initial, penalty=penalty
            )
            try:
                purchases = plan_purchases(
                    miles, prices, trip, range_miles=tank, mpg=mpg,
                    initial_gallons=initial / mpg, stop_penalty=penalty,
                )
            except Infeasible:
                self.assertEqual(expected, math.inf, f'case {case}: a plan exists')
                continue
            actual = sum(p.cost for p in purchases) + penalty * len(purchases)
            self.assertAlmostEqual(actual, expected, places=6, msg=f'case {case}')
