import asyncio
import logging

from helpers.api import SearchLevel, fetch_all_deals, resolve_street_id
from helpers.export import enrich, save

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

TARGET_STREETS = [
    ("חיפה", "אהוד"),
    ("חיפה", "יותם"),
]


async def fetch_street(city_name: str, street_name: str) -> None:
    logging.info(f"Resolving: {street_name}, {city_name}")
    street_id = await resolve_street_id(city_name, street_name)
    logging.info(f"  Street ID: {street_id} — fetching deals...")
    deals = await fetch_all_deals(street_id, SearchLevel.STREET)
    df = enrich(deals)
    path = save(df, city_name, street_name)
    logging.info(f"  Saved {len(df)} deals → {path}")


async def run() -> None:
    for city_name, street_name in TARGET_STREETS:
        await fetch_street(city_name, street_name)


if __name__ == "__main__":
    asyncio.run(run())
