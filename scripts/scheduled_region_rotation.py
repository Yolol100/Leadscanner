"""Deterministic, bounded Dutch-region rotation for scheduled lead research.

Only public municipality names. Keep outreach/identity data in private sources.
"""

from datetime import date

REGIONS_PER_DAY = 8
REGIONS = (
    "Groningen",
    "Amersfoort",
    "Dordrecht",
    "Venlo",
    "Alkmaar",
    "Leeuwarden",
    "Breda",
    "Gouda",
    "Assen",
    "Apeldoorn",
    "Leiden",
    "Roosendaal",
    "Zwolle",
    "Hengelo",
    "Hoorn",
    "Veenendaal",
    "Lelystad",
    "Deventer",
    "Delft",
    "Heerlen",
    "Arnhem",
    "Nijmegen",
    "Hilversum",
    "Bergen op Zoom",
    "Utrecht",
    "Woerden",
    "Emmen",
    "Weert",
    "Haarlem",
    "Amsterdam",
    "Doetinchem",
    "Gorinchem",
    "Den Haag",
    "Zoetermeer",
    "Ede",
    "Waalwijk",
    "Middelburg",
    "Goes",
    "Sittard",
    "Zeist",
    "Eindhoven",
    "Helmond",
    "Alphen aan den Rijn",
    "Schagen",
    "Maastricht",
    "Vlaardingen",
    "Harderwijk",
    "Meppel",
    "Rotterdam",
    "Amstelveen",
    "Oss",
    "Hoogeveen",
    "Enschede",
    "Tilburg",
    "Purmerend",
    "Zutphen",
    "Zaandam",
    "Drachten",
    "Heerenveen",
    "Rijswijk",
    "Diemen",
    "Dieren",
    "Houten",
    "Veldhoven",
)


def scheduled_regions(day: date) -> tuple[str, ...]:
    """Use a new city group daily; rotate within groups every eight days."""
    if type(day) is not date:
        raise ValueError("scheduled_region_day_invalid")
    group_count = len(REGIONS) // REGIONS_PER_DAY
    group = day.toordinal() % group_count
    cycle = (day.toordinal() // group_count) % REGIONS_PER_DAY
    base = group * REGIONS_PER_DAY
    return tuple(REGIONS[base + (cycle + index) % REGIONS_PER_DAY]
                 for index in range(REGIONS_PER_DAY))
