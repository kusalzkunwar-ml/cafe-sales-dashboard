"""Generate a realistic, deliberately messy POS export for a fictional Sydney cafe.

The cafe ("Tallow & Bean", Strathfield) is invented. Every row is synthetic,
made with a fixed seed so the dataset is reproducible.

Output: data/raw/pos_export_raw.csv (one row per line item, Nov 2025 - Oct 2026)
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261119
rng = np.random.default_rng(SEED)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "pos_export_raw.csv"

# name, category, price (AUD), unit cost (AUD), base popularity weight
MENU = [
    ("Flat White", "Coffee", 5.00, 1.10, 22),
    ("Cappuccino", "Coffee", 5.00, 1.10, 12),
    ("Latte", "Coffee", 5.20, 1.20, 16),
    ("Long Black", "Coffee", 4.50, 0.80, 8),
    ("Iced Latte", "Coffee", 6.50, 1.50, 5),
    ("Chai Latte", "Tea & Other", 5.50, 1.30, 5),
    ("English Breakfast Tea", "Tea & Other", 4.50, 0.60, 3),
    ("Hot Chocolate", "Tea & Other", 5.50, 1.40, 4),
    ("Fresh Orange Juice", "Cold Drinks", 7.50, 2.60, 3),
    ("Iced Coffee", "Cold Drinks", 7.50, 2.00, 3),
    ("Smoothie", "Cold Drinks", 9.00, 3.20, 2),
    ("Banana Bread", "Bakery", 6.00, 1.50, 6),
    ("Croissant", "Bakery", 5.50, 1.80, 7),
    ("Almond Croissant", "Bakery", 7.00, 2.40, 4),
    ("Muffin", "Bakery", 5.00, 1.40, 3),
    ("Avocado Toast", "Brunch", 18.50, 5.80, 5),
    ("Big Breakfast", "Brunch", 24.00, 8.90, 3),
    ("Eggs Benedict", "Brunch", 21.00, 6.70, 3),
    ("Acai Bowl", "Brunch", 17.00, 6.10, 2),
    ("Ham & Cheese Toastie", "Lunch", 12.00, 3.60, 4),
    ("Chicken Wrap", "Lunch", 15.00, 5.20, 3),
    ("Caesar Salad", "Lunch", 17.50, 5.90, 2),
]
MENU_DF = pd.DataFrame(MENU, columns=["item", "category", "price", "cost", "weight"])

STAFF = ["Mia", "Josh", "Priya", "Liam", "Sofia"]

# Hours open: 6:30am - 3:00pm weekdays, 7:00am - 3:00pm weekends
def hourly_orders(weekday: int) -> dict[int, float]:
    if weekday < 5:  # Mon-Fri: commuter spike, smaller lunch bump, dead afternoon
        base = {6: 8, 7: 26, 8: 30, 9: 16, 10: 10, 11: 11, 12: 15, 13: 9, 14: 4}
        if weekday == 0:  # Mondays are quiet after lunch
            base = {k: (v * 0.6 if k >= 12 else v) for k, v in base.items()}
    else:  # weekends: late brunch peak
        base = {7: 8, 8: 18, 9: 30, 10: 34, 11: 28, 12: 20, 13: 12, 14: 6}
    return base


def season_factor(month: int) -> float:
    # Southern hemisphere: busier in spring/summer, January dip (holidays)
    return {1: 0.82, 2: 0.95, 3: 1.0, 4: 0.97, 5: 0.93, 6: 0.88, 7: 0.86,
            8: 0.92, 9: 1.0, 10: 1.05, 11: 1.08, 12: 1.02}[month]


def item_weights(hour: int, weekend: bool, month: int) -> np.ndarray:
    w = MENU_DF["weight"].to_numpy(dtype=float).copy()
    cat = MENU_DF["category"].to_numpy()
    summer = month in (11, 12, 1, 2)
    w[cat == "Brunch"] *= (2.4 if weekend and 8 <= hour <= 12 else 0.5 if hour >= 12 else 1.0)
    w[cat == "Lunch"] *= (2.5 if 11 <= hour <= 14 else 0.1)
    w[cat == "Cold Drinks"] *= (2.2 if summer else 0.6)
    w[MENU_DF["item"].to_numpy() == "Iced Latte"] *= (2.0 if summer else 0.5)
    w[cat == "Bakery"] *= (1.4 if hour <= 10 else 0.8)
    return w / w.sum()


def build() -> pd.DataFrame:
    rows = []
    order_id = 100000
    days = pd.date_range("2025-11-01", "2026-10-31", freq="D")
    for day in days:
        wd, month = day.weekday(), day.month
        if day.month == 12 and day.day in (25, 26) or (day.month == 1 and day.day == 1):
            continue  # closed public holidays
        growth = 1 + 0.12 * ((day - days[0]).days / 365)  # slow business growth
        for hour, mean in hourly_orders(wd).items():
            n_orders = rng.poisson(mean * season_factor(month) * growth)
            probs = item_weights(hour, wd >= 5, month)
            for _ in range(n_orders):
                order_id += 1
                minute = int(rng.integers(30 if hour == 6 else 0, 60))
                n_items = 1 + rng.poisson(0.9 if wd >= 5 else 0.5)
                staff = STAFF[int(rng.integers(0, len(STAFF)))]
                pay = rng.choice(["Card", "Cash", "Mobile"], p=[0.68, 0.10, 0.22])
                for line_no, idx in enumerate(rng.choice(len(MENU_DF), size=n_items, p=probs), 1):
                    m = MENU_DF.iloc[idx]
                    qty = 1 if rng.random() > 0.08 else 2
                    rows.append([order_id, line_no, day, f"{hour:02d}:{minute:02d}", m["item"],
                                 m["category"], qty, m["price"], m["cost"], pay, staff])
    return pd.DataFrame(rows, columns=["order_id", "line_no", "date", "time", "item", "category",
                                       "qty", "unit_price", "unit_cost", "payment", "staff"])


def make_messy(df: pd.DataFrame) -> pd.DataFrame:
    """Introduce the kinds of mess a real POS export has."""
    df = df.copy()
    n = len(df)
    # 1. Mixed date formats (system change in May 2026)
    d = df["date"]
    df["date"] = np.where(d < "2026-05-01", d.dt.strftime("%d/%m/%Y"), d.dt.strftime("%Y-%m-%d"))
    # 2. Inconsistent item names: case, trailing spaces, typos
    variants = {"Flat White": ["flat white", "Flat white ", "FLAT WHITE"],
                "Cappuccino": ["Capuccino", "cappuccino"],
                "Avocado Toast": ["Avo Toast", "avocado toast"],
                "Ham & Cheese Toastie": ["Ham and Cheese Toastie"],
                "Banana Bread": ["banana bread "]}
    for good, bads in variants.items():
        mask = (df["item"] == good) & (rng.random(n) < 0.12)
        df.loc[mask, "item"] = rng.choice(bads, size=mask.sum())
    # 3. Prices stored as text with "$", some blank
    df["unit_price"] = df["unit_price"].map(lambda p: f"${p:.2f}")
    df.loc[rng.random(n) < 0.006, "unit_price"] = ""
    # 4. Typo prices (decimal slipped): $50.00 instead of $5.00
    typo = rng.random(n) < 0.0008
    df.loc[typo, "unit_price"] = df.loc[typo, "unit_price"].map(
        lambda s: f"${float(s[1:]) * 10:.2f}" if s else s)
    # 5. Missing categories
    df.loc[rng.random(n) < 0.015, "category"] = ""
    # 6. Payment method spelled differently
    df["payment"] = df["payment"].replace({"Card": "Card"})
    pm = rng.random(n)
    df.loc[(df["payment"] == "Card") & (pm < 0.1), "payment"] = "card"
    df.loc[(df["payment"] == "Mobile") & (pm < 0.3), "payment"] = "Apple Pay"
    df.loc[(df["payment"] == "Cash") & (pm < 0.2), "payment"] = "CASH"
    # 7. Refunds as negative quantities
    df.loc[rng.random(n) < 0.004, "qty"] *= -1
    # 8. Duplicate rows (export glitch)
    dupes = df.sample(frac=0.012, random_state=SEED)
    df = pd.concat([df, dupes]).sort_index(kind="stable").reset_index(drop=True)
    return df.drop(columns=["unit_cost"])


if __name__ == "__main__":
    clean = build()
    # Unit costs are supplied separately, like a supplier price list would be
    MENU_DF[["item", "category", "price", "cost"]].rename(
        columns={"price": "menu_price", "cost": "unit_cost"}
    ).to_csv(ROOT / "data" / "raw" / "menu_costs.csv", index=False)
    messy = make_messy(clean)
    messy.to_csv(OUT, index=False)
    print(f"{len(messy):,} rows -> {OUT}")
