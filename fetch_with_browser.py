"""
Browser-assisted deal fetcher. Opens a real Chrome window, waits for you to
trigger one search on nadlan.gov.il, intercepts the server token automatically,
then fetches all deals for TARGET_STREETS.

Usage:
  pip install playwright
  playwright install chromium
  python fetch_with_browser.py

The browser window stays open so reCAPTCHA sees a real human. Once you do
one search, the script captures the token and does the rest.
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
import time
import urllib.request

import aiohttp
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SECRET = "90c3e620192348f1bd46fcd9138c3c68"
DOMAIN = "www.nadlan.gov.il"
DEAL_API = "https://api.nadlan.gov.il/deal-data"
S3_SETTLEMENT = "https://data.nadlan.gov.il/api/pages/settlement/buy/{}.json"

API_HEADERS = {
    "accept": "*/*",
    "content-type": "text/plain",
    "origin": f"https://{DOMAIN}",
    "referer": f"https://{DOMAIN}/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

TARGET_STREETS = [
    ("חיפה", "4000", "אהוד"),
    ("חיפה", "4000", "יותם"),
]

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


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
    return json.dumps({"##": jwt[::-1]})


def decode_response(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(gzip.decompress(base64.b64decode(text + "==")).decode("utf-8"))
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}


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
    for s in streets:
        if street_name in s.get("title", ""):
            return s["id"]
    raise ValueError(f"Street '{street_name}' not found")


async def fetch_all_deals(server_token, street_id):
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT")
    all_items = []
    page = 1

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx)) as session:
        while True:
            body = make_request_body(street_id, "streetCode", server_token, page)
            async with session.post(DEAL_API, data=body, headers=API_HEADERS) as r:
                result = decode_response(await r.read())

            if not isinstance(result, dict):
                break

            status = result.get("statusCode", "?")
            data = result.get("data", {})
            items = data.get("items", [])
            total = data.get("total_rows", 0)

            if status != 200 or not items:
                if page == 1:
                    logging.warning(f"API status={status}, rows={total}. Token may be expired.")
                break

            all_items.extend(items)
            logging.info(f"  Page {page}: {len(items)} deals ({len(all_items)}/{total})")

            if len(all_items) >= total:
                break
            page += 1
            await asyncio.sleep(0.5)

    return all_items


def save_deals(deals, city_name, street_name):
    os.makedirs(DATA_DIR, exist_ok=True)
    df = pd.DataFrame(deals)
    safe = lambda s: s.replace(" ", "_").replace("/", "-")
    path = os.path.join(DATA_DIR, f"{safe(city_name)}_{safe(street_name)}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path, df


async def capture_token_and_fetch():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Install playwright first:")
        print("  pip install playwright")
        print("  playwright install chromium")
        return

    server_token = None
    token_event = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Intercept token-verify responses
        async def handle_response(response):
            nonlocal server_token
            if "token-verify" in response.url and response.status == 200:
                try:
                    body = await response.text()
                    # The response is the UUID token as a plain string or JSON
                    token = body.strip().strip('"')
                    if len(token) > 10:
                        server_token = token
                        logging.info(f"Captured server token: {token}")
                        token_event.set()
                except Exception as e:
                    logging.error(f"Failed to read token-verify response: {e}")

        page.on("response", handle_response)

        await page.goto("https://www.nadlan.gov.il/")
        logging.info("Browser opened. Please search for any street to trigger reCAPTCHA.")
        logging.info("Waiting for token-verify response...")

        # Wait up to 5 minutes for user to trigger a search
        try:
            await asyncio.wait_for(token_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            logging.error("Timed out waiting for token. Please search on the site.")
            await browser.close()
            return

        logging.info(f"Got token! Fetching deals for {len(TARGET_STREETS)} streets...")

        for city_name, settlement_id, street_name in TARGET_STREETS:
            logging.info(f"Looking up: {street_name}, {city_name}")
            street_id = lookup_street_id(settlement_id, street_name)
            logging.info(f"  Street ID: {street_id}")

            deals = await fetch_all_deals(server_token, street_id)
            if not deals:
                logging.warning(f"  No deals for {street_name}. Token may have expired.")
                # Wait for a new token
                logging.info("  Try searching again in the browser to get a fresh token.")
                token_event.clear()
                try:
                    await asyncio.wait_for(token_event.wait(), timeout=120)
                except asyncio.TimeoutError:
                    logging.error("  No new token received. Skipping.")
                    continue
                deals = await fetch_all_deals(server_token, street_id)

            if deals:
                path, df = save_deals(deals, city_name, street_name)
                logging.info(f"  Saved {len(df)} deals -> {path}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(capture_token_and_fetch())
