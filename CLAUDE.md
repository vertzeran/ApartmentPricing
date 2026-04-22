# ApartmentPricing — Claude Handoff

## What this project is
Downloads Israeli real estate transaction data from nadlan.gov.il for specific streets and saves as CSV.

## Current state: reverse-engineering blocked by reCAPTCHA

`helpers/api.py` uses the OLD REST API (`www.nadlan.gov.il/Nadlan.REST/`) which no longer returns data — it serves the React SPA HTML. The real API has been fully reverse-engineered but is blocked by reCAPTCHA.

---

## Real API — fully reverse-engineered

### Endpoint
```
POST https://api.nadlan.gov.il/deal-data
Content-Type: text/plain
Body: {"##": "<reversed HS256 JWT>"}
```

### Token generation flow
1. Generate `sk` inner JWT: `{"domain": "www.nadlan.gov.il", "exp": now+120}` signed with `SECRET`
2. Build payload:
   ```json
   {"base_id": "4000", "base_name": "settlmentID", "fetch_number": 1,
    "type_order": "dealDate_down", "sk": "<sk_jwt>", "token": "<server_token>",
    "exp": now+120, "domain": "www.nadlan.gov.il"}
   ```
3. Sign that payload as HS256 JWT with `SECRET`
4. Reverse the entire JWT string character-by-character
5. POST `{"##": reversed_jwt}` with `Content-Type: text/plain`

### Signing key (hardcoded in JS bundle)
```
SECRET = "90c3e620192348f1bd46fcd9138c3c68"
```

### The blocker: `token` field requires reCAPTCHA
The `token` field is NOT a random UUID — it's a **server-issued token obtained after reCAPTCHA Enterprise verification**:

1. Browser runs reCAPTCHA Enterprise (site key: `6LeFXPIrAAAAADG099BKMLMI85eElTM5qon0SdRH`)
2. Browser POSTs `{"token": recaptcha_token}` to `https://api.nadlan.gov.il/token-verify`
3. Server returns a UUID (e.g. `"c7eb0de7-7791-46a0-beda-713a0e3f7ad5"`)
4. That UUID is used as `token` in the JWT payload

Without a valid server token, every request returns `{"statusCode": 405, "data": {"total_rows": 0, ...}}`.

The `token-verify` endpoint rejects invalid reCAPTCHA tokens:
- Empty/null → `{"ok": false, "error": "Missing token"}`
- Invalid string → `{"ok": false, "error": "Token verification failed"}`

### Response format (successful)
Body is base64(gzip(json)):
```python
json.loads(gzip.decompress(base64.b64decode(body + "==")).decode("utf-8"))
# → {"statusCode": 200, "data": {"total_rows": N, "total_fetch": N, "total_page": N, "items": [...]}}
```

---

## Data IDs and base_name values

| base_name | meaning | example ID |
|-----------|---------|------------|
| `settlmentID` | city/settlement | `4000` (Haifa) |
| `streetCode` | street | `40001223` (8-digit) |
| `neighborhoodId` | neighborhood | `65210819` (8-digit) |
| `setlCode` | settlement (alt) | same as settlmentID |
| `addressId` | specific address | from address lookup |

Street and neighborhood IDs come from S3 JSON files:
- Settlement overview: `https://data.nadlan.gov.il/api/pages/settlement/buy/{id}.json`
  - `otherSettlmentStreets` → array of `{id, name}` for streets (8-digit IDs like `40001223`)
  - `otherNeighborhoods` → array of `{id, name}` for neighborhoods (8-digit IDs like `65210819`)

S3 deal files at `data.nadlan.gov.il/api/deals/` return 403 — only the protected API works.

---

## App config
```
GET https://www.nadlan.gov.il/config.json
```
Key fields: `api_base`, `s3_page_base`, `recaptcha_token_url`, `recaptcha_token_site_key`

---

## Possible next steps to unblock

**Option A — 2captcha/anti-captcha service** (~$2/1000 tokens)
- Use their API to solve reCAPTCHA Enterprise programmatically
- Call `token-verify` with the solved token to get the server UUID
- Valid for ~2 minutes (Tf=120), so solve fresh per session

**Option B — Playwright with real Chrome**
- Drive a real browser to get a valid reCAPTCHA token automatically
- Extract the server token from the response and use it for subsequent API calls

**Option C — Old REST API fallback**
- `helpers/api.py` currently uses `www.nadlan.gov.il/Nadlan.REST/GetAssestAndDeals`
- This endpoint may still be live but returns HTML for browser requests
- Try with direct API headers to check if it still works

---

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, defines `TARGET_STREETS` |
| `helpers/api.py` | **OUTDATED** — uses old REST API, needs full rewrite |
| `helpers/export.py` | Parses deals, saves UTF-8-sig CSV to `data/` |
| `debug_api.py` | Working debug script for the new API (signing verified correct) |
| `requirements.txt` | Dependencies |
| `setup.bat` | Creates venv and installs deps |

## Target streets (main.py)
```python
TARGET_STREETS = [
    ("חיפה", "אהוד"),
    ("חיפה", "יותם"),
]
```

## Known working signing code (from debug_api.py)
```python
import base64, hashlib, hmac, json, time, uuid

SECRET = "90c3e620192348f1bd46fcd9138c3c68"
DOMAIN = "www.nadlan.gov.il"

def _b64u(d): return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
def _sign(p, key_bytes):
    h = _b64u(json.dumps({"alg":"HS256"}, separators=(",",":")).encode())
    b = _b64u(json.dumps(p, separators=(",",":")).encode())
    s = hmac.new(key_bytes, f"{h}.{b}".encode(), hashlib.sha256).digest()
    return f"{h}.{b}.{_b64u(s)}"

def make_token(base_id, base_name, server_token, page=1):
    exp = int(time.time()) + 120
    sk  = _sign({"domain": DOMAIN, "exp": exp}, SECRET.encode())
    payload = {
        "base_id": str(base_id), "base_name": base_name,
        "fetch_number": page, "type_order": "dealDate_down",
        "sk": sk, "token": server_token,
        "exp": exp, "domain": DOMAIN,
    }
    return _sign(payload, SECRET.encode())[::-1]
```
