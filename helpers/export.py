import os
from datetime import datetime

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def enrich(deals: list) -> pd.DataFrame:
    rows = []
    for deal in deals:
        row = deal.copy()
        try:
            row["block"], row["parcel"], row["lot"] = deal["GUSH"].split("-")
        except (KeyError, ValueError):
            pass
        try:
            row["price"] = int(deal["DEALAMOUNT"].replace(",", ""))
        except (KeyError, ValueError):
            pass
        try:
            row["deal_date"] = datetime.fromisoformat(deal["DEALDATETIME"])
        except (KeyError, ValueError):
            pass
        rows.append(row)
    return pd.DataFrame(rows)


def save(df: pd.DataFrame, city_name: str, street_name: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    safe = lambda s: s.replace(" ", "_").replace("/", "-")
    path = os.path.join(DATA_DIR, f"{safe(city_name)}_{safe(street_name)}.csv")
    # utf-8-sig adds BOM so Excel opens Hebrew text correctly
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
