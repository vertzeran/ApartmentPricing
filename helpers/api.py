import asyncio
import ssl
from enum import IntEnum

import aiohttp
from tenacity import retry, stop_after_attempt, wait_random_exponential

API_URL = "https://www.nadlan.gov.il/Nadlan.REST/"

HEADERS = {
    "Referer": "https://www.nadlan.gov.il/",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


class SearchLevel(IntEnum):
    CITY = 2
    NEIGHBORHOOD = 3
    STREET = 4
    GUSH_PARCEL = 6
    ADDRESS = 7


def _session():
    # Workaround for RSA cipher negotiation failures on some servers
    # https://stackoverflow.com/a/71007463
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.set_ciphers("DEFAULT")
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_ctx),
        headers=HEADERS,
    )


@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
async def get_streets_for_city(city_name: str) -> list:
    async with _session() as session:
        async with session.get(
            API_URL + "Main/GetStreetsListByCityAndStartsWith",
            params={"CityName": city_name, "startWithKey": -1},
        ) as r:
            r.raise_for_status()
            return await r.json(content_type=None)


async def resolve_street_id(city_name: str, street_name: str) -> int:
    streets = await get_streets_for_city(city_name)
    if not streets:
        raise ValueError(f"No streets found for city: {city_name!r}")

    first = streets[0]
    name_field = next(
        (k for k in first if any(w in k.upper() for w in ("NAME", "DESC", "SHEM"))), None
    )
    id_field = next(
        (k for k in first if any(w in k.upper() for w in ("CODE", "ID", "KEY", "KOD"))), None
    )
    if not name_field or not id_field:
        raise ValueError(
            f"Cannot detect field names in street list response. "
            f"Available keys: {list(first.keys())}"
        )

    match = next((s for s in streets if street_name in str(s.get(name_field, ""))), None)
    if not match:
        available = [s.get(name_field) for s in streets[:10]]
        raise ValueError(
            f"Street {street_name!r} not found in {city_name!r}. "
            f"Sample streets: {available}"
        )
    return match[id_field]


@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
async def _fetch_page(session: aiohttp.ClientSession, object_id: int, level: SearchLevel, page: int) -> dict:
    payload = {
        "ObjectID": str(object_id),
        "CurrentLavel": int(level),  # sic — typo is in the API
        "ObjectKey": "UNIQ_ID",
        "ObjectIDType": "text",
        "PageNo": page + 1,
    }
    async with session.post(API_URL + "Main/GetAssestAndDeals", json=payload) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


async def fetch_all_deals(object_id: int, level: SearchLevel = SearchLevel.STREET) -> list:
    results = []
    async with _session() as session:
        page = 0
        while True:
            data = await _fetch_page(session, object_id, level, page)
            results.extend(data.get("AllResults", []))
            if data.get("IsLastPage", True):
                break
            page += 1
            await asyncio.sleep(1)
    return results
