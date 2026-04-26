# ApartmentPricing

Downloads real estate transaction data from the Israeli government database ([nadlan.gov.il](https://www.nadlan.gov.il)) for specific streets, and saves the results as CSV files for offline analysis.

## Setup

```bat
setup.bat
call venv\Scripts\activate
```

## Usage

The nadlan.gov.il API requires a server token obtained via reCAPTCHA on the website. You need to grab one from your browser before running the script.

### Step 1 — Get a server token

1. Open https://www.nadlan.gov.il in Chrome
2. Open DevTools (**F12**) → **Network** tab
3. Search for any street on the site (doesn't matter which — it just triggers the reCAPTCHA)
4. In the Network tab, filter for `token-verify` — click on that request
5. Go to the **Response** tab — copy the UUID from the `token` field, e.g. `"69e520d7-92c1-4515-9ddd-d5c323c8ff35"`

### Step 2 — Run

```bat
python fetch_with_token.py <your-token-uuid>
```

The token is valid for ~2 minutes. The script fetches all deals for every street in `TARGET_STREETS` and saves CSVs to `data/`.

### Configuring target streets

Edit `TARGET_STREETS` in `fetch_with_token.py`:

```python
TARGET_STREETS = [
    ("חיפה", "4000", "אהוד"),      # (city_name, settlement_id, street_name)
    ("חיפה", "4000", "יותם"),
]
```

Settlement IDs can be found at `https://data.nadlan.gov.il/api/pages/settlement/buy/{id}.json`. Haifa is `4000`.

## Output

CSVs are saved to `data/<city>_<street>.csv`, encoded as UTF-8 with BOM so Excel opens Hebrew correctly.

Each deal record includes: address, deal date, price, rooms, floor, area (sqm), price per sqm, building floors, year built, and more.

## Project Structure

```
├── data/                  # downloaded CSVs (git-ignored)
├── fetch_with_token.py    # main script — fetches deals using a browser token
├── fetch_with_browser.py  # alternative — uses Playwright to capture token automatically
├── requirements.txt
└── setup.bat              # creates/recreates the virtual environment
```

## Notes

- The token from `token-verify` expires after ~2 minutes. Grab a fresh one if the script reports 0 deals.
- Street IDs are looked up automatically from the (public, no-auth) S3 data endpoint.
- A 0.5-second delay is added between paginated requests.
