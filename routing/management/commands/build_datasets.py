"""
One-off dataset builder. Its outputs are committed to the repository, so you
only need to run it again if the raw price file changes.

    python manage.py build_datasets --geonames /path/to/US.txt

Inputs
    data/fuel-prices-for-be-assessment.csv   raw OPIS price list (no coordinates)
    US.txt                                   GeoNames dump for the US
                                             (https://download.geonames.org/export/dump/US.zip)
Outputs
    data/fuel_stations.csv    one row per US station, with a mean price and lat/lng
    data/us_places.csv.gz     "City, ST" gazetteer used to geocode API inputs locally
"""

import csv
import gzip
import re
from collections import defaultdict
from statistics import fmean

from django.conf import settings
from django.core.management.base import BaseCommand

from routing.services.gazetteer import US_STATES, compact_key, place_key

RAW_PRICES = settings.DATA_DIR / 'fuel-prices-for-be-assessment.csv'
STATIONS_OUT = settings.DATA_DIR / 'fuel_stations.csv'
PLACES_OUT = settings.DATA_DIR / 'us_places.csv.gz'

# Station "cities" that are not populated places in GeoNames, located by hand
# from other GeoNames features (a marina and a travel-centre casino).
MANUAL_LOCATIONS = {
    ('Willow Beach', 'AZ'): (35.87026, -114.65942),
    ('Pueblo Of Acoma', 'NM'): (35.07583, -107.55556),
}

ADMIN_PREFIX = re.compile(r'^(town|township|city|village|borough) of ', re.IGNORECASE)

# GeoNames dump columns.
NAME, ASCII_NAME, ALT_NAMES, LAT, LNG, FEATURE_CLASS = 1, 2, 3, 4, 5, 6
STATE, POPULATION = 10, 14


class Command(BaseCommand):
    help = 'Geocode the raw fuel price list and build the local gazetteer (one-off).'

    def add_arguments(self, parser):
        parser.add_argument('--geonames', required=True, help='Path to the GeoNames US.txt dump.')

    def handle(self, *args, **options):
        places, fallbacks = self.read_geonames(options['geonames'])
        self.write_places(places)
        self.write_stations(places, fallbacks)

    def read_geonames(self, path):
        """
        Returns ``places`` (populated places keyed by normalised name, the most
        populous one winning a name clash) and ``fallbacks`` (alternate names
        and non-city features, only used for stations that match nothing else).
        """
        places, fallbacks = {}, {}
        with open(path, encoding='utf-8') as dump:
            for line in dump:
                row = line.rstrip('\n').split('\t')
                state = row[STATE]
                if state not in US_STATES:
                    continue
                entry = {
                    'name': row[NAME],
                    'state': state,
                    'latitude': float(row[LAT]),
                    'longitude': float(row[LNG]),
                    'population': int(row[POPULATION] or 0),
                }
                if row[FEATURE_CLASS] == 'P':
                    for name in {row[NAME], row[ASCII_NAME]}:
                        key = place_key(name, state)
                        if key not in places or entry['population'] > places[key]['population']:
                            places[key] = entry
                    alt_names = row[ALT_NAMES].split(',') if row[ALT_NAMES] else []
                elif row[FEATURE_CLASS] == 'A':  # "Town of Corinth", "Township of Crescent"
                    alt_names = [ADMIN_PREFIX.sub('', row[NAME])]
                else:
                    continue
                for name in alt_names:
                    fallbacks.setdefault(compact_key(name, state), entry)
        return places, fallbacks

    def write_places(self, places):
        unique = {id(entry): entry for entry in places.values()}.values()
        rows = sorted(unique, key=lambda e: (e['state'], e['name'], -e['population']))
        with gzip.open(PLACES_OUT, 'wt', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['name', 'state', 'latitude', 'longitude', 'population'])
            for entry in rows:
                writer.writerow([
                    entry['name'], entry['state'],
                    f"{entry['latitude']:.5f}", f"{entry['longitude']:.5f}", entry['population'],
                ])
        self.stdout.write(f'{PLACES_OUT.name}: {len(rows):,} places')

    def write_stations(self, places, fallbacks):
        compact_places = {}
        for entry in places.values():
            key = compact_key(entry['name'], entry['state'])
            if key not in compact_places or entry['population'] > compact_places[key]['population']:
                compact_places[key] = entry

        with open(RAW_PRICES, encoding='utf-8-sig', newline='') as handle:
            raw_rows = list(csv.DictReader(handle))

        # The raw file repeats a station once per price observation.
        grouped = defaultdict(list)
        for row in raw_rows:
            grouped[int(row['OPIS Truckstop ID'])].append(row)

        stations, skipped_non_us, unmatched = [], 0, []
        for opis_id, rows in sorted(grouped.items()):
            first = rows[0]
            city, state = first['City'].strip(), first['State'].strip().upper()
            if state not in US_STATES:  # Canadian provinces
                skipped_non_us += 1
                continue
            place = (
                places.get(place_key(city, state))
                or compact_places.get(compact_key(city, state))
                or fallbacks.get(compact_key(city, state))
            )
            if place is None and (city, state) in MANUAL_LOCATIONS:
                latitude, longitude = MANUAL_LOCATIONS[city, state]
                place = {'latitude': latitude, 'longitude': longitude}
            if place is None:
                unmatched.append(f'{city}, {state}')
                continue
            stations.append([
                opis_id,
                ' '.join(first['Truckstop Name'].split()),
                ' '.join(first['Address'].split()),
                city,
                state,
                first['Rack ID'].strip(),
                f"{fmean(float(r['Retail Price']) for r in rows):.3f}",
                f"{place['latitude']:.5f}",
                f"{place['longitude']:.5f}",
            ])

        with open(STATIONS_OUT, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow([
                'opis_id', 'name', 'address', 'city', 'state', 'rack_id',
                'price', 'latitude', 'longitude',
            ])
            writer.writerows(stations)

        self.stdout.write(
            f'{STATIONS_OUT.name}: {len(stations):,} stations from {len(raw_rows):,} raw rows '
            f'({skipped_non_us} non-US skipped, {len(unmatched)} not geocoded)'
        )
        for label in unmatched:
            self.stdout.write(f'  not geocoded: {label}')
