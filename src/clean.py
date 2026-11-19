"""Clean the raw POS export and write a data-quality report.

Input:  data/raw/pos_export_raw.csv, data/raw/menu_costs.csv
Output: data/clean/sales_clean.csv, reports/data_quality.md
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean" / "sales_clean.csv"
REPORT = ROOT / "reports" / "data_quality.md"

# Known spelling variants found while profiling the raw item column
ITEM_FIXES = {
    "capuccino": "Cappuccino",
    "avo toast": "Avocado Toast",
    "ham and cheese toastie": "Ham & Cheese Toastie",
}
PAYMENT_FIXES = {"card": "Card", "cash": "Cash", "apple pay": "Mobile", "mobile": "Mobile"}


def clean(raw: pd.DataFrame, menu: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    log: list[tuple[str, int]] = [("Rows in raw export", len(raw))]
    df = raw.copy()

    # 1. Exact duplicate rows from the export glitch
    before = len(df)
    df = df.drop_duplicates()
    log.append(("Exact duplicate rows removed", before - len(df)))

    # 2. Dates: two formats (DD/MM/YYYY before May 2026, ISO after)
    iso = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    au = pd.to_datetime(df["date"], format="%d/%m/%Y", errors="coerce")
    df["date"] = iso.fillna(au)
    log.append(("Dates converted from DD/MM/YYYY", int(iso.isna().sum())))
    assert df["date"].notna().all(), "unparsed dates remain"

    # 3. Item names: trim, fix case, map known variants to the menu name
    canon = {name.lower(): name for name in menu["item"]}
    canon.update(ITEM_FIXES)
    key = df["item"].str.strip().str.lower()
    fixed = key.map(canon)
    log.append(("Item names standardised", int((fixed != df["item"]).sum())))
    assert fixed.notna().all(), f"unknown items: {sorted(key[fixed.isna()].unique())}"
    df["item"] = fixed

    # 4. Category: fill blanks from the menu
    df = df.merge(menu[["item", "category", "menu_price", "unit_cost"]], on="item",
                  how="left", suffixes=("_raw", ""))
    log.append(("Missing categories filled from menu", int((df["category_raw"].fillna("") == "").sum())))
    df = df.drop(columns="category_raw")

    # 5. Prices: "$5.00" text -> number; blanks and 10x typos -> menu price
    price = pd.to_numeric(df["unit_price"].astype(str).str.replace("$", "", regex=False), errors="coerce")
    blank = price.isna()
    typo = ~blank & np.isclose(price, df["menu_price"] * 10)
    log.append(("Blank prices filled from menu", int(blank.sum())))
    log.append(("Typo prices (10x menu) corrected", int(typo.sum())))
    price[blank | typo] = df.loc[blank | typo, "menu_price"]
    df["unit_price"] = price

    # 6. Payment method labels
    before_pay = df["payment"].copy()
    df["payment"] = df["payment"].str.strip().str.lower().map(PAYMENT_FIXES)
    log.append(("Payment labels standardised", int((before_pay != df["payment"]).sum())))
    assert df["payment"].notna().all()

    # 7. Refunds stay in (negative qty) but are flagged so they can be reported
    df["is_refund"] = df["qty"] < 0
    log.append(("Refund lines flagged (kept, negative)", int(df["is_refund"].sum())))

    # 8. Derived fields
    df["revenue"] = (df["qty"] * df["unit_price"]).round(2)
    df["cost"] = (df["qty"] * df["unit_cost"]).round(2)
    df["gross_profit"] = df["revenue"] - df["cost"]
    df["hour"] = df["time"].str[:2].astype(int)
    df["weekday"] = df["date"].dt.day_name()
    df["month"] = df["date"].dt.to_period("M").astype(str)

    df = df.drop(columns="menu_price").sort_values(["date", "time", "order_id"]).reset_index(drop=True)
    log.append(("Rows in clean file", len(df)))
    return df, log


def write_report(df: pd.DataFrame, log: list[tuple[str, int]]) -> None:
    lines = ["# Data quality report", "",
             "What the cleaning script found and fixed in the raw POS export.", "",
             "| Check | Rows |", "| --- | ---: |"]
    lines += [f"| {name} | {count:,} |" for name, count in log]
    lines += ["", f"Date range: {df['date'].min():%d %b %Y} to {df['date'].max():%d %b %Y}.",
              f"Orders: {df['order_id'].nunique():,}. Net revenue: ${df['revenue'].sum():,.2f}.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raw = pd.read_csv(RAW / "pos_export_raw.csv", dtype={"unit_price": str, "category": str}, keep_default_na=False)
    raw["qty"] = raw["qty"].astype(int)
    menu = pd.read_csv(RAW / "menu_costs.csv")
    df, log = clean(raw, menu)
    df.to_csv(CLEAN, index=False, date_format="%Y-%m-%d")
    write_report(df, log)
    for name, count in log:
        print(f"{name:<40} {count:>8,}")
