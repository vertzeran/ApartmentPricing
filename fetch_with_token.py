"""
Semi-manual deal fetcher for nadlan.gov.il.

Usage:
  1. Open https://www.nadlan.gov.il in Chrome
  2. Open DevTools (F12) → Network tab
  3. Search for any street (e.g. type "אהוד" in the search box and click)
  4. In Network tab, find the request to "token-verify"
  5. Click it → Response tab → copy the UUID string (e.g. "c7eb0de7-7791-46a0-beda-713a0e3f7ad5")
  6. Run:  python fetch_with_token.py <that-uuid>

The token is valid for ~2 minutes. The script fetches all pages for all
TARGET_STREETS and saves CSVs to data/.
"""

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import ssl
import sys
import time
import urllib.request

import aiohttp
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SECRET = "90c3e620192348f1bd46fcd9138c3c68"
DOMAIN = "www.nadlan.gov.il"
DEAL_API = "https://api.nadlan.gov.il/deal-data"
S3_SETTLEMENT = "https://data.nadlan.gov.il/api/pages/settlement/buy/{}.json"

HEADERS = {
    "accept": "*/*",
    "content-type": "text/plain",
    "origin": f"https://{DOMAIN}",
    "referer": f"https://{DOMAIN}/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# (city_name, settlement_id, street_name)
# Settlement IDs: Haifa=4000, Tel Aviv=5000, Jerusalem=3000, etc.
# Full list: https://data.nadlan.gov.il/api/pages/settlement/buy/{id}.json
TARGET_STREETS = [
    ("חיפה", "4000", "אהוד"),
    ("חיפה", "4000", "יותם"),
    ("חיפה", "4000", "יוכבד"),
]

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# --- Signing ---

def _b64u(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def _sign(payload, key_bytes):
    h = _b64u(json.dumps({"alg": "HS256"}, separators=(",", ":")).encode())
    b = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    s = hmac.new(key_bytes, f"{h}.{b}".encode(), hashlib.sha256).digest()
    return f"{h}.{b}.{_b64u(s)}"


def make_request_body(base_id, base_name, server_token, page=1):
    exp = int(time.time()) + 120
    sk = _sign({"domain": DOMAIN, "exp": exp}, SECRET.encode())
    payload = {
        "base_id": str(base_id),
        "base_name": base_name,
        "fetch_number": page,
        "type_order": "dealDate_down",
        "sk": sk,
        "token": server_token,
        "exp": exp,
        "domain": DOMAIN,
    }
    jwt = _sign(payload, SECRET.encode())
    reversed_jwt = jwt[::-1]
    return json.dumps({"##": reversed_jwt})


def decode_response(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(gzip.decompress(base64.b64decode(text + "==")).decode("utf-8"))
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}


# --- Street lookup (no auth needed) ---

def lookup_street_id(settlement_id, street_name):
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT")
    url = S3_SETTLEMENT.format(settlement_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        data = json.loads(r.read())
    streets = data.get("otherSettlmentStreets", [])
    for s in streets:
        if s.get("title") == street_name:
            return s["id"]
    # Partial match fallback
    for s in streets:
        if street_name in s.get("title", ""):
            return s["id"]
    available = [s["title"] for s in streets[:20]]
    raise ValueError(f"Street '{street_name}' not found. Sample: {available}")


# --- Fetch deals ---

async def fetch_all_deals(server_token, street_id, base_name="streetCode"):
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT")
    all_items = []
    page = 1

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ctx)
    ) as session:
        while True:
            body = make_request_body(street_id, base_name, server_token, page)
            async with session.post(DEAL_API, data=body, headers=HEADERS) as r:
                raw = await r.read()
                result = decode_response(raw)

            if not isinstance(result, dict):
                logging.error(f"Unexpected response: {str(result)[:200]}")
                break

            status = result.get("statusCode", "?")
            data = result.get("data", {})
            items = data.get("items", [])
            total = data.get("total_rows", 0)

            if status != 200 or not items:
                if page == 1:
                    logging.warning(f"API returned status={status}, total_rows={total}. Token may be invalid.")
                break

            all_items.extend(items)
            logging.info(f"  Page {page}: got {len(items)} deals (total so far: {len(all_items)}/{total})")

            if len(all_items) >= total:
                break
            page += 1
            await asyncio.sleep(0.5)

    return all_items


# --- Save ---

def save_deals(deals, city_name, street_name):
    os.makedirs(DATA_DIR, exist_ok=True)
    df = pd.DataFrame(deals)
    safe = lambda s: s.replace(" ", "_").replace("/", "-")
    path = os.path.join(DATA_DIR, f"{safe(city_name)}_{safe(street_name)}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path, df


# --- Main ---

async def run(server_token):
    for city_name, settlement_id, street_name in TARGET_STREETS:
        logging.info(f"Looking up street: {street_name}, {city_name}")
        street_id = lookup_street_id(settlement_id, street_name)
        logging.info(f"  Street ID: {street_id}")

        logging.info(f"  Fetching deals...")
        deals = await fetch_all_deals(server_token, street_id)

        if not deals:
            logging.warning(f"  No deals returned for {street_name}. Token may have expired.")
            continue

        path, df = save_deals(deals, city_name, street_name)
        logging.info(f"  Saved {len(df)} deals -> {path}")
        logging.info(f"  Columns: {list(df.columns)}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    token = sys.argv[1].strip().strip('"').strip("'")
    logging.info(f"Using server token: {token}")
    asyncio.run(run(token))
