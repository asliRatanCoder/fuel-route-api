# Fuel Route API

A Django API that takes a start and a finish location in the USA and returns

* the driving route (as GeoJSON, plus a link to an interactive map),
* the **cheapest places to refuel** along it for a vehicle with a **500-mile range**,
* the **total money spent on fuel** at **10 miles per gallon**,

using the supplied OPIS fuel price list.

It makes **exactly one call** to a free routing API per trip (zero for a repeated
trip), and the rest of the work — geocoding, finding stations along the route,
optimising the purchases — takes about **6 ms** for a coast-to-coast drive.

```
GET /api/route/?start=New York, NY&finish=Los Angeles, CA
```

| | |
|---|---|
| Stack | Django 6.1, Django REST Framework, numpy / scipy |
| Routing | [OSRM](https://project-osrm.org) public server — free, no API key |
| Map | GeoJSON in the response + a Leaflet / OpenStreetMap page at `/` |

## Quick start

Requires Python 3.12+ (Django 6.1).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_data        # 6,626 stations + the US gazetteer, ~5 s
python manage.py runserver
```

Then either

* open <http://localhost:8000/> for the interactive map, or
* import `postman_collection.json` into Postman and run the requests top to bottom
  (each one carries a short description and a few assertions).

```bash
python manage.py test             # 34 tests, no network needed
```

## API

### `GET /api/route/` · `POST /api/route/`

Parameters go in the query string (GET) or a JSON body (POST).

| Parameter | Required | Description |
|---|---|---|
| `start`, `finish` | yes | `"City, ST"`, `"City, State"`, a street address, or `"lat,lng"` |
| `initial_fuel_gallons` | no | Fuel on board at departure, `0`–`50`. Default: a full tank (`50`) |
| `stop_penalty` | no | Dollar value of the time one stop costs; see [the optimiser](#3-choosing-the-stops). Default `5`; `0` = pure minimum fuel cost |

Response for `Chicago, IL → Denver, CO` (route geometry omitted):

```jsonc
{
  "start":  {"query": "Chicago, IL", "resolved_as": "Chicago, IL", "latitude": 41.85003, "longitude": -87.65005, "geocoder": "gazetteer"},
  "finish": {"query": "Denver, CO",  "resolved_as": "Denver, CO",  "latitude": 39.73915, "longitude": -104.9847, "geocoder": "gazetteer"},
  "route":   {"distance_miles": 1004.8, "duration_hours": 17.86},
  "vehicle": {"range_miles": 500.0, "miles_per_gallon": 10.0, "tank_gallons": 50.0, "initial_fuel_gallons": 50.0},
  "summary": {
    "total_fuel_cost": 142.05,            // <- total money spent on fuel
    "total_gallons_purchased": 50.49,
    "fuel_used_gallons": 100.48,
    "average_price_per_gallon": 2.813,
    "number_of_stops": 2,
    "stations_considered": 202
  },
  "fuel_stops": [
    {
      "stop": 1, "opis_id": 69840, "name": "KUM & GO #0370", "address": "I-80, EXIT 439 & SR-370",
      "city": "Gretna", "state": "NE", "latitude": 41.14083, "longitude": -96.23974,
      "route_mile": 484.5, "miles_off_route": 2.1, "price_per_gallon": 2.921,
      "fuel_on_arrival_gallons": 1.5, "gallons_purchased": 6.0, "cost": 17.52
    },
    {
      "stop": 2, "opis_id": 68368, "name": "AKAL TRAVEL CENTER", "address": "I-80 EX 360",
      "city": "Waco", "state": "NE", "latitude": 40.89696, "longitude": -97.46338,
      "route_mile": 560.1, "miles_off_route": 5.2, "price_per_gallon": 2.799,
      "fuel_on_arrival_gallons": 0.0, "gallons_purchased": 44.49, "cost": 124.53
    }
  ],
  "notes": [],
  "map": {
    "url": "http://localhost:8000/?start=Chicago%2C+IL&finish=Denver%2C+CO",
    "geojson": {"type": "FeatureCollection", "features": ["route LineString", "start", "finish", "one Point per fuel stop"]}
  },
  "meta": {"external_api_calls": {"routing": 1, "geocoding": 0}, "served_from_cache": false, "elapsed_ms": 191.7}
}
```

This small example shows what "optimal" means here. The cheapest fuel on the
route is in Waco, NE ($2.799) at mile 560 — 60 miles beyond what the starting
tank can reach. So the plan buys **only 6 gallons** at mile 484, just enough to
roll into Waco empty, and buys everything else there.

`map.geojson` is a standard FeatureCollection (paste it into <https://geojson.io>);
`map.url` opens the same plan on the built-in map page, served from cache.

Errors share one envelope, `{"error": {"code": "...", "message": "..."}}`:

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_request` | missing / out-of-range parameters (`fields` lists them) |
| 400 | `location_not_found`, `location_outside_usa` | a location can't be resolved inside the USA |
| 422 | `no_route` | no drivable route (e.g. Hawaii) |
| 422 | `no_feasible_fuel_plan` | the price list has no station for longer than the vehicle's range |
| 503 | `upstream_unavailable` | the routing / geocoding service is down or timed out |

## How it works

```
"New York, NY" ──► geocode (local DB) ─┐
                                       ├─► OSRM route (the 1 API call) ─► stations along
"Los Angeles, CA" ► geocode (local DB) ─┘    34k-point polyline            the route (KD-tree)
                                                                                 │
                       JSON + GeoJSON  ◄── purchases: dynamic programme ◄────────┘
```

### 1. Keeping external calls to one

* **Routing** — one OSRM request returns distance, duration and the full
  geometry. Nothing else is asked of it: station matching happens locally.
* **Geocoding** — spending two more calls to geocode the inputs would triple the
  budget, so the repo bundles a gazetteer of 178k US populated places (from
  GeoNames) and resolves `"City, ST"` / `"City, State"` with an indexed DB lookup.
  `"lat,lng"` needs no lookup at all. Only free-form street addresses fall back
  to Nominatim (one call, cached for a day). `meta.external_api_calls` reports
  what each request actually spent.
* **Caching** — routes and finished plans are cached (Django cache framework), so
  a repeated trip, the map page for a plan just computed, or the same trip with
  different fuel settings never calls the router again.

### 2. Finding stations along the route

The price list has no coordinates, so a one-off command
(`build_datasets`) geocodes each station to its city using GeoNames and writes
`data/fuel_stations.csv`; all 6,626 US stations were matched.

At request time the ~6.6k stations live in numpy arrays (loaded once per
process). The route is re-sampled to a point every half mile — OSRM describes a
long straight highway with very few vertices, so measuring to the raw vertices
would miss stations sitting mid-segment — and a KD-tree over those points gives,
for every station in the route's bounding box, its distance from the route and
the trip mile at which it is passed. Stations within 10 miles count as "on the
route" (setting `ROUTE_CORRIDOR_MILES`). ~1.5 ms.

### 3. Choosing the stops

The optimiser minimises **fuel cost + `stop_penalty` × number of stops**, subject
to never running dry and never overfilling the tank.

The penalty matters. Pure cost minimisation has a classic greedy solution, but
on real prices it chases every cent: New York → Los Angeles comes out at **17
stops**, several of them for a gallon or two. Pricing a stop at $5 of the
driver's time gives **6 stops for $9.97 more** (+1.4 %) — a plan someone would
actually drive. `stop_penalty=0` returns the pure minimum.

It is solved exactly with dynamic programming over *(station, fuel in tank)*.
The trip is divided into N equal steps of about a mile; `cost[f]` is the cheapest
way to be at the current station holding `f` steps of fuel.

* driving to the next station shifts the array by the distance;
* buying from level `f` up to `f'` costs `cost[f] + (f'−f)·c + penalty`, i.e.
  `min_f(cost[f] − f·c) + f'·c + penalty` — a running minimum, so each station
  costs O(tank) numpy work rather than O(tank²).

Because the steps add up to the trip exactly, gallons and dollars are exact.
~3 ms for 459 candidate stations. The test suite checks the result against a
deliberately naive brute-force implementation on 300 random instances.

### Performance

Coast to coast (New York → Los Angeles, 2,794 mi, 34,537 route points):

| Step | Time |
|---|---|
| decode polyline (vectorised) | 1.7 ms |
| re-sample route | 1.3 ms |
| stations along route | 1.5 ms |
| optimise purchases | 3.2 ms |
| **all local work** | **≈ 6 ms** |
| OSRM request | ≈ 200 ms on a warm connection |
| repeated request (cache) | ≈ 4 ms end to end |

The OSRM client keeps one HTTP session alive; only the first request after
start-up pays an extra ~0.8 s for DNS + TLS.

## Assumptions and data notes

* **The vehicle leaves with a full tank** (the natural reading of "maximum range
  of 500 miles"), so `total_fuel_cost` is what is bought on the road, and a trip
  under 500 miles costs nothing and needs no stop. `summary.fuel_used_gallons`
  shows the whole trip's consumption; `initial_fuel_gallons` changes the
  assumption.
* The tank may arrive empty at a stop or at the destination — the brief gives a
  hard 500-mile range and no reserve.
* **Duplicate rows**: 678 stations appear several times with different prices
  and no timestamp. Each station is collapsed to one row at its **mean** price
  (taking the minimum would favour stations simply for having more rows).
* **City-level coordinates**: addresses like `I-44, EXIT 283 & US-69` are not
  something a free geocoder resolves reliably, so stations sit at their city's
  centre; hence the 10-mile corridor. Detours to a station are not added to the
  trip distance.
* **Canadian stations** (112) are dropped — trips are within the USA. A
  consequence: Alaska ↔ lower-48 routes cross Canada and cannot be fuelled.
* **California** has only 8 stations in the file, all in the far south-east, so
  e.g. Seattle → Los Angeles down I-5 honestly returns `no_feasible_fuel_plan`
  (877 miles without a listed station) rather than inventing a stop.

## Project layout

```
config/                     settings, urls
routing/
  models.py                 FuelStation, Place
  serializers.py  views.py  urls.py  exceptions.py
  services/
    planner.py              orchestration + caching + response shape
    geocoding.py            lat,lng -> gazetteer -> Nominatim fallback
    gazetteer.py            place-name normalisation
    osrm.py                 the routing client (one call)
    polyline.py             vectorised polyline decoder
    stations.py             in-memory station index, KD-tree corridor search
    optimizer.py            the dynamic programme (pure numpy, no Django)
    geo.py                  haversine & friends
  management/commands/
    load_data.py            CSVs -> database
    build_datasets.py       one-off: raw price list + GeoNames -> data/*.csv
  templates/routing/map.html
  tests/
data/
  fuel-prices-for-be-assessment.csv   the file supplied with the assignment
  fuel_stations.csv                   de-duplicated + geocoded (generated)
  us_places.csv.gz                    gazetteer (generated)
postman_collection.json
```

Configuration is by environment variable, with working defaults:
`OSRM_BASE_URL` (point it at a self-hosted OSRM for production),
`ROUTE_CORRIDOR_MILES`, `FUEL_STOP_PENALTY_USD`, `EXTERNAL_API_TIMEOUT`,
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`.

## With more time

* Geocode stations to their actual highway exit and charge detour miles.
* A configurable fuel reserve instead of allowing an empty tank on arrival.
* Redis for the cache (shared across workers) and a self-hosted OSRM.
* Ask OSRM for alternative routes when the fastest one has a stretch without fuel.

## Data attribution

Place names and coordinates: [GeoNames](https://www.geonames.org), CC BY 4.0.
Routing and map tiles: © OpenStreetMap contributors, via OSRM and Nominatim.
