"""
Load the committed datasets into the database (idempotent).

    python manage.py load_data
"""

import csv
import gzip
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import FuelStation, Place
from routing.services.gazetteer import compact_key, place_key

STATIONS_CSV = settings.DATA_DIR / 'fuel_stations.csv'
PLACES_CSV = settings.DATA_DIR / 'us_places.csv.gz'
BATCH_SIZE = 5000


class Command(BaseCommand):
    help = 'Load fuel stations and the US places gazetteer into the database.'

    @transaction.atomic
    def handle(self, *args, **options):
        self.load_stations()
        self.load_places()

    def load_stations(self):
        with open(STATIONS_CSV, encoding='utf-8', newline='') as handle:
            stations = [
                FuelStation(
                    opis_id=int(row['opis_id']),
                    name=row['name'],
                    address=row['address'],
                    city=row['city'],
                    state=row['state'],
                    rack_id=int(row['rack_id']) if row['rack_id'] else None,
                    price=Decimal(row['price']),
                    latitude=float(row['latitude']),
                    longitude=float(row['longitude']),
                )
                for row in csv.DictReader(handle)
            ]
        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(stations, batch_size=BATCH_SIZE)
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(stations):,} fuel stations'))

    def load_places(self):
        places = {}
        with gzip.open(PLACES_CSV, 'rt', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                place = Place(
                    key=place_key(row['name'], row['state']),
                    compact_key=compact_key(row['name'], row['state']),
                    name=row['name'],
                    state=row['state'],
                    latitude=float(row['latitude']),
                    longitude=float(row['longitude']),
                    population=int(row['population']),
                )
                # Same name twice in one state: keep the more populous place.
                current = places.get(place.key)
                if current is None or place.population > current.population:
                    places[place.key] = place
        Place.objects.all().delete()
        Place.objects.bulk_create(places.values(), batch_size=BATCH_SIZE)
        self.stdout.write(self.style.SUCCESS(f'Loaded {len(places):,} places'))
