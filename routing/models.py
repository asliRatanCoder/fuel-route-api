from django.db import models


class FuelStation(models.Model):
    """
    One truck stop from the OPIS price file, collapsed to a single row per
    station and geocoded to its city (see the ``build_datasets`` command).
    """

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(
        max_digits=6, decimal_places=3, help_text='Retail price, USD per gallon.'
    )
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        ordering = ['opis_id']

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state}) ${self.price}'


class Place(models.Model):
    """
    US populated place (GeoNames). Lets the API geocode "City, ST" inputs
    locally instead of spending an external API call on it.
    """

    key = models.CharField(
        max_length=160, unique=True, help_text='Normalised "name|ST" lookup key.'
    )
    compact_key = models.CharField(
        max_length=160, db_index=True, help_text='Same key with spaces removed.'
    )
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    latitude = models.FloatField()
    longitude = models.FloatField()
    population = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'{self.name}, {self.state}'
