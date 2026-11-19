"""Build the dashboard data file, the key findings and the Excel summary workbook.

Input:  data/clean/sales_clean.csv
Output: dashboard/data.js, reports/findings.md, excel/cafe_sales_summary.xlsx
"""
import json
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parents[1]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOURS = list(range(6, 15))
SUMMER, WINTER = ["2025-11", "2025-12", "2026-01", "2026-02"], ["2026-06", "2026-07", "2026-08"]


def aggregates(df: pd.DataFrame) -> dict:
    """Per-month building blocks, so the dashboard can filter by period in the browser."""
    months = sorted(df["month"].unique())
    orders = df.drop_duplicates("order_id")
    days_open = df.groupby("month")["date"].nunique()
    out = {"months": months, "days": DAYS, "hours": HOURS, "kpi": {}, "heat": {}, "items": {}, "cats": {}}
    menu = df.groupby("item").agg(category=("category", "first"), price=("unit_price", "median"),
                                  unit_cost=("unit_cost", "first"))
    out["menu"] = {i: {"category": r.category, "price": round(r.price, 2),
                       "margin": round((r.price - r.unit_cost) / r.price, 4)} for i, r in menu.iterrows()}
    for m in months:
        d, o = df[df["month"] == m], orders[orders["month"] == m]
        out["kpi"][m] = {"revenue": round(d["revenue"].sum(), 2), "gp": round(d["gross_profit"].sum(), 2),
                         "orders": int(o["order_id"].nunique()), "days": int(days_open[m]),
                         "refunds": round(-d.loc[d["is_refund"], "revenue"].sum(), 2)}
        # orders per weekday x hour, and how many of each weekday the cafe opened that month
        cnt = o.groupby(["weekday", "hour"]).size()
        nday = d.drop_duplicates("date")["weekday"].value_counts()
        out["heat"][m] = {"orders": [[int(cnt.get((wd, h), 0)) for h in HOURS] for wd in DAYS],
                          "ndays": [int(nday.get(wd, 0)) for wd in DAYS]}
        it = d.groupby("item").agg(units=("qty", "sum"), revenue=("revenue", "sum"), gp=("gross_profit", "sum"))
        out["items"][m] = {i: [int(r.units), round(r.revenue, 2), round(r.gp, 2)] for i, r in it.iterrows()}
        out["cats"][m] = {c: round(v, 2) for c, v in d.groupby("category")["revenue"].sum().items()}
    return out


def findings(df: pd.DataFrame) -> list[dict]:
    orders = df.drop_duplicates("order_id")
    ndays = df.drop_duplicates("date")["weekday"].value_counts()

    def per_day_hour(mask_days, hours):
        o = orders[orders["weekday"].isin(mask_days) & orders["hour"].isin(hours)]
        return len(o) / (sum(ndays[d] for d in mask_days) * len(hours))

    mon_pm = per_day_hour(["Monday"], [12, 13, 14])
    oth_pm = per_day_hour(["Tuesday", "Wednesday", "Thursday", "Friday"], [12, 13, 14])
    mon_rev = df[(df["weekday"] == "Monday") & (df["hour"] >= 13)]["revenue"].sum() / ndays["Monday"]

    wk = df[df["weekday"].isin(["Saturday", "Sunday"])]
    brunch_share = wk[wk["hour"].between(9, 11)]["revenue"].sum() / wk["revenue"].sum()

    cold = df[df["category"] == "Cold Drinks"].groupby("month")["revenue"].sum()
    cold_ratio = cold[SUMMER].mean() / cold[WINTER].mean()

    items = df.groupby("item").agg(units=("qty", "sum"), gp=("gross_profit", "sum"), rev=("revenue", "sum"))
    items["margin"] = items["gp"] / items["rev"]
    food = items[df.groupby("item")["category"].first().isin(["Brunch", "Lunch"])]
    plow = food.sort_values("margin").iloc[0]
    plow_name = food.sort_values("margin").index[0]
    best = items["gp"].idxmax()

    return [
        {"title": "Monday afternoons barely cover staff",
         "text": f"Monday 12-3pm averages {mon_pm:.1f} orders an hour, against {oth_pm:.1f} on other weekdays. "
                 f"After 1pm a Monday brings in about ${mon_rev:,.0f}. Closing at 1pm on Mondays, or running a "
                 f"lunch deal, is worth testing."},
        {"title": "Weekend brunch is the engine",
         "text": f"9-11am on Saturday and Sunday makes {brunch_share:.0%} of weekend revenue. "
                 f"Extra kitchen staff in that window protects the busiest hours."},
        {"title": "Cold drinks are seasonal",
         "text": f"Cold drinks sell {cold_ratio:.1f}x more per month in summer (Nov-Feb) than in winter (Jun-Aug). "
                 f"Order stock and promote them from October."},
        {"title": f"{plow_name} has the thinnest margin",
         "text": f"It keeps only {plow.margin:.0%} of its price as gross margin, the lowest of the brunch and lunch "
                 f"dishes, on {plow.units:,.0f} sold a year. A $2 price rise or cheaper ingredients would lift "
                 f"profit. {best} is the biggest single profit earner."},
    ]


def write_excel(df: pd.DataFrame, path: Path) -> None:
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2A78D6")
    money = '"$"#,##0'

    # Monthly sheet with live formulas
    ws = wb.active
    ws.title = "Monthly"
    monthly = df.groupby("month").agg(revenue=("revenue", "sum"), gp=("gross_profit", "sum"),
                                      orders=("order_id", "nunique")).reset_index()
    ws.append(["Month", "Revenue", "Gross profit", "Orders", "Avg order value", "Gross margin"])
    for i, r in enumerate(monthly.itertuples(), start=2):
        ws.append([pd.Period(r.month).strftime("%b %Y"), round(r.revenue, 2), round(r.gp, 2), r.orders,
                   f"=B{i}/D{i}", f"=C{i}/B{i}"])
    last = len(monthly) + 1
    ws.append(["Total", f"=SUM(B2:B{last})", f"=SUM(C2:C{last})", f"=SUM(D2:D{last})",
               f"=B{last + 1}/D{last + 1}", f"=C{last + 1}/B{last + 1}"])
    for c in ws[1]:
        c.font, c.fill = head, fill
    for row in ws.iter_rows(min_row=2):
        row[1].number_format = row[2].number_format = money
        row[3].number_format = "#,##0"
        row[4].number_format = '"$"#,##0.00'
        row[5].number_format = "0.0%"
    for c in ws[last + 1]:
        c.font = Font(bold=True)
    chart = LineChart()
    chart.title, chart.y_axis.title, chart.height, chart.width = "Monthly revenue", "AUD", 8, 18
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
    ws.add_chart(chart, "H2")

    # Products sheet
    wp = wb.create_sheet("Products")
    prod = df.groupby(["item", "category"]).agg(units=("qty", "sum"), revenue=("revenue", "sum"),
                                                gp=("gross_profit", "sum")).reset_index()
    prod = prod.sort_values("revenue", ascending=False)
    wp.append(["Item", "Category", "Units sold", "Revenue", "Gross profit", "Gross margin"])
    for i, r in enumerate(prod.itertuples(), start=2):
        wp.append([r.item, r.category, int(r.units), round(r.revenue, 2), round(r.gp, 2), f"=E{i}/D{i}"])
    for c in wp[1]:
        c.font, c.fill = head, fill
    for row in wp.iter_rows(min_row=2):
        row[2].number_format = "#,##0"
        row[3].number_format = row[4].number_format = money
        row[5].number_format = "0.0%"
    bar = BarChart()
    bar.type, bar.title, bar.height, bar.width = "bar", "Revenue by item", 12, 16
    bar.add_data(Reference(wp, min_col=4, min_row=1, max_row=len(prod) + 1), titles_from_data=True)
    bar.set_categories(Reference(wp, min_col=1, min_row=2, max_row=len(prod) + 1))
    bar.y_axis.number_format = money
    wp.add_chart(bar, "H2")

    # Clean data as an Excel table (filterable)
    wd = wb.create_sheet("Clean data")
    cols = ["order_id", "line_no", "date", "time", "item", "category", "qty", "unit_price",
            "revenue", "gross_profit", "payment", "staff", "is_refund"]
    wd.append(cols)
    for r in df[cols].itertuples(index=False):
        wd.append([r.order_id, r.line_no, r.date.date(), r.time, r.item, r.category, r.qty, r.unit_price,
                   r.revenue, r.gross_profit, r.payment, r.staff, bool(r.is_refund)])
    ref = f"A1:{get_column_letter(len(cols))}{len(df) + 1}"
    t = Table(displayName="Sales", ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    wd.add_table(t)
    for col in wd.iter_cols(min_col=3, max_col=3, min_row=2):
        for c in col:
            c.number_format = "dd/mm/yyyy"

    for sheet in (ws, wp, wd):
        sheet.freeze_panes = "A2"
        for i, col in enumerate(sheet.iter_cols(min_row=1, max_row=1), 1):
            sheet.column_dimensions[get_column_letter(i)].width = max(12, len(str(col[0].value)) + 4)
    wp.column_dimensions["A"].width = 24
    ws.column_dimensions["A"].width = 12
    wd.column_dimensions["E"].width = 24
    for c in ws["A"]:
        c.alignment = Alignment(horizontal="left")
    wb.save(path)


if __name__ == "__main__":
    df = pd.read_csv(ROOT / "data" / "clean" / "sales_clean.csv", parse_dates=["date"])
    data = aggregates(df)
    data["findings"] = findings(df)
    js = "window.CAFE = " + json.dumps(data, separators=(",", ":")) + ";\n"
    (ROOT / "dashboard" / "data.js").write_text(js, encoding="utf-8")
    md = ["# Key findings", ""] + [f"**{f['title']}.** {f['text']}\n" for f in data["findings"]]
    (ROOT / "reports" / "findings.md").write_text("\n".join(md), encoding="utf-8")
    write_excel(df, ROOT / "excel" / "cafe_sales_summary.xlsx")
    print(f"data.js {len(js) / 1024:.0f} KB")
    for f in data["findings"]:
        print("-", f["title"], ":", f["text"])
