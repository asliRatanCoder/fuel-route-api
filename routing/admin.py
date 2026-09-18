from django.contrib import admin

from routing.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('opis_id', 'name', 'city', 'state', 'price')
    list_filter = ('state',)
    search_fields = ('name', 'city', '=opis_id')
    ordering = ('price',)
