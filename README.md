# ApartmentPricing

Downloads real estate transaction data from the Israeli government database ([nadlan.gov.il](https://www.nadlan.gov.il)) for specific streets, and saves the results as CSV files for offline analysis.

## Setup

```bat
setup.bat
call venv\Scripts\activate
```

## Usage

Edit `TARGET_STREETS` in `main.py` with the streets you want (Hebrew city and street names):

```python
TARGET_STREETS = [
    ("תל אביב - יפו", "דיזנגוף"),
    ("תל אביב - יפו", "רוטשילד"),
]
```

Then run:

```bat
python main.py
```

Output CSVs are saved to `data/<city>_<street>.csv`, encoded as UTF-8 with BOM so Excel opens Hebrew text correctly.

## Project Structure

```
├── data/           # downloaded CSVs (git-ignored)
├── helpers/
│   ├── api.py      # nadlan.gov.il REST API calls and street ID resolution
│   └── export.py   # data enrichment and CSV export
├── main.py         # entry point — define target streets here
├── requirements.txt
└── setup.bat       # creates/recreates the virtual environment
```

## Data Source

The [nadlan.gov.il](https://www.nadlan.gov.il) REST API (`/Nadlan.REST/`). Each deal record includes price, date, address, floor, rooms, area, and cadastral identifiers (block/parcel/lot).

## Notes

- City names must match the API exactly, e.g. `"תל אביב - יפו"` (spaces around the dash).
- The API has rate limiting — a 1-second delay is added between paginated requests automatically.
- If street resolution fails, the error message lists available street names to help correct the spelling.
