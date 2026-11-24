"""Отчети за разходите: текстови и HTML."""

from __future__ import annotations

import html
from datetime import date

from . import catalog, textutil as tx

MONTHS_BG = [
    "януари", "февруари", "март", "април", "май", "юни",
    "юли", "август", "септември", "октомври", "ноември", "декември",
]


def month_label(month: str) -> str:
    try:
        year, mon = month.split("-")
        return f"{MONTHS_BG[int(mon) - 1]} {year}"
    except (ValueError, IndexError):
        return month


def collect(db, month: str = None, year=None) -> dict:
    purchases = sorted(db.purchases, key=lambda p: p["date"])
    if month:
        purchases = [p for p in purchases if p["date"][:7] == month]
        label = month_label(month)
    elif year:
        purchases = [p for p in purchases if p["date"][:4] == str(year)]
        label = f"{year} г."
    else:
        label = "всички периоди"

    products = catalog.products_by_id(db)
    total = round(sum(float(p.get("total") or 0) for p in purchases), 2)
    count = len(purchases)
    avg = round(total / count, 2) if count else 0.0

    by_store: dict = {}
    by_cat: dict = {}
    by_month: dict = {}
    for purchase in purchases:
        store = catalog.store_name(db, purchase.get("store_id"))
        by_store[store] = round(by_store.get(store, 0) + float(purchase["total"]), 2)
        key = purchase["date"][:7]
        by_month[key] = round(by_month.get(key, 0) + float(purchase["total"]), 2)
        for line in purchase.get("items", []):
            product = products.get(line.get("product_id"))
            category = (product or {}).get("category") or "Други"
            by_cat[category] = round(by_cat.get(category, 0) + float(line.get("total") or 0), 2)

    budget = None
    if month and db.settings.get("budget_month"):
        budget = round(float(db.settings["budget_month"]), 2)

    store_names = {s["id"]: s["name"] for s in db.stores}

    def ranked(mapping):
        return sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "label": label,
        "month": month,
        "year": year,
        "total": total,
        "count": count,
        "average": avg,
        "budget": budget,
        "spent_share": round(total / budget * 100, 1) if budget else None,
        "remaining": round(budget - total, 2) if budget else None,
        "by_store": ranked(by_store),
        "by_category": ranked(by_cat),
        "by_month": sorted(by_month.items()),
        "purchases": purchases,
        "store_names": store_names,
        "generated": date.today().isoformat(),
    }


def store_of(rep: dict, purchase: dict) -> str:
    return rep["store_names"].get(purchase.get("store_id")) or "Други"


def _share(value: float, total: float) -> str:
    if not total:
        return "—"
    return f"{value / total * 100:.1f}%"


def format_text(rep: dict) -> str:
    lines = []
    lines.append(f"ОТЧЕТ — {rep['label']}")
    lines.append("=" * 46)
    lines.append(f"Общо: {tx.money(rep['total'])}   Покупки: {rep['count']}   "
                 f"Средна кошница: {tx.money(rep['average'])}")
    if rep["budget"]:
        lines.append(f"Бюджет: {tx.money(rep['budget'])}   Похарчено: {rep['spent_share']}%   "
                     f"Остават: {tx.money(rep['remaining'])}")
    if not rep["purchases"]:
        lines.append("")
        lines.append("Няма записани покупки за този период.")
        return "\n".join(lines)

    if rep["by_month"] and len(rep["by_month"]) > 1:
        lines.append("")
        lines.append("По месеци")
        for month, value in rep["by_month"]:
            lines.append(f"  {month_label(month):<16} {tx.money(value):>10}   "
                         f"{_share(value, rep['total'])}")

    lines.append("")
    lines.append("По магазини")
    for name, value in rep["by_store"]:
        lines.append(f"  {name:<18} {tx.money(value):>10}   {_share(value, rep['total'])}")

    lines.append("")
    lines.append("По категории")
    for name, value in rep["by_category"]:
        lines.append(f"  {name:<18} {tx.money(value):>10}   {_share(value, rep['total'])}")

    lines.append("")
    lines.append("Покупки")
    for purchase in rep["purchases"]:
        store = store_of(rep, purchase)
        lines.append(f"  {purchase['date']}  {store:<18} "
                     f"{len(purchase.get('items', []))} поз.  {tx.money(purchase['total'])}"
                     f"  [{purchase['id']}]")
    return "\n".join(lines)


def format_html(rep: dict) -> str:
    esc = html.escape
    total = rep["total"] or 0

    def rows(mapping, total_value):
        out = []
        for name, value in mapping:
            pct = (value / total_value * 100) if total_value else 0
            out.append(
                f"<tr><td>{esc(str(name))}</td><td class='num'>{tx.money(value)}</td>"
                f"<td class='num'>{pct:.1f}%</td></tr>"
            )
        return "".join(out) or "<tr><td colspan='3' class='muted'>няма данни</td></tr>"

    budget_html = ""
    if rep["budget"]:
        pct = min(rep["spent_share"], 100)
        over = " over" if rep["spent_share"] > 100 else ""
        budget_html = f"""
  <div class="card">
    <div class="label">Бюджет за месеца</div>
    <div class="value">{tx.money(rep['budget'])}</div>
    <div class="bar"><span class="fill{over}" style="width:{pct}%"></span></div>
    <div class="muted">Похарчено {rep['spent_share']}% · остават {tx.money(rep['remaining'])}</div>
  </div>"""

    purchase_rows = []
    for purchase in rep["purchases"]:
        store = store_of(rep, purchase)
        names = ", ".join(esc(i["name"]) for i in purchase.get("items", []))
        purchase_rows.append(
            f"<tr><td>{esc(purchase['date'])}</td><td>{esc(store)}</td>"
            f"<td>{names}</td><td class='num'>{tx.money(purchase['total'])}</td></tr>"
        )
    purchases_html = "".join(purchase_rows) or \
        "<tr><td colspan='4' class='muted'>няма записани покупки</td></tr>"

    month_rows = ""
    if len(rep["by_month"]) > 1:
        month_rows = "<h2>По месеци</h2><table><thead><tr><th>Месец</th><th class='num'>Сума</th></tr></thead><tbody>"
        for month, value in rep["by_month"]:
            month_rows += f"<tr><td>{esc(month_label(month))}</td><td class='num'>{tx.money(value)}</td></tr>"
        month_rows += "</tbody></table>"

    return f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчет за покупки — {esc(rep['label'])}</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --ink:#1c2430; --muted:#6b7684; --line:#e5e8ec; --accent:#2f6fed; --ok:#1f9d55; --bad:#d64545; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 16px; background:var(--bg); color:var(--ink);
         font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif; }}
  .wrap {{ max-width:860px; margin:0 auto; }}
  h1 {{ font-size:24px; margin:0 0 4px; }}
  h2 {{ font-size:17px; margin:28px 0 8px; }}
  .sub {{ color:var(--muted); margin:0 0 20px; font-size:14px; }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; }}
  .card {{ flex:1 1 190px; background:var(--card); border:1px solid var(--line);
           border-radius:12px; padding:14px 16px; }}
  .label {{ color:var(--muted); font-size:13px; }}
  .value {{ font-size:24px; font-weight:650; margin-top:2px; }}
  .muted {{ color:var(--muted); font-size:13px; }}
  .bar {{ height:8px; background:#eceff3; border-radius:6px; overflow:hidden; margin:10px 0 6px; }}
  .bar .fill {{ display:block; height:100%; background:var(--accent); }}
  .bar .fill.over {{ background:var(--bad); }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
           border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
  th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); font-size:14px; }}
  th {{ background:#fbfcfd; color:var(--muted); font-weight:600; }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  footer {{ margin-top:26px; color:var(--muted); font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Отчет за покупки — {esc(rep['label'])}</h1>
  <p class="sub">Генериран на {esc(rep['generated'])}</p>
  <div class="cards">
    <div class="card"><div class="label">Общо</div><div class="value">{tx.money(rep['total'])}</div></div>
    <div class="card"><div class="label">Покупки</div><div class="value">{rep['count']}</div></div>
    <div class="card"><div class="label">Средна кошница</div><div class="value">{tx.money(rep['average'])}</div></div>
    {budget_html}
  </div>
  <h2>По магазини</h2>
  <table><thead><tr><th>Магазин</th><th class="num">Сума</th><th class="num">Дял</th></tr></thead>
  <tbody>{rows(rep['by_store'], total)}</tbody></table>
  <h2>По категории</h2>
  <table><thead><tr><th>Категория</th><th class="num">Сума</th><th class="num">Дял</th></tr></thead>
  <tbody>{rows(rep['by_category'], total)}</tbody></table>
  {month_rows}
  <h2>Покупки</h2>
  <table><thead><tr><th>Дата</th><th>Магазин</th><th>Позиции</th><th class="num">Сума</th></tr></thead>
  <tbody>{purchases_html}</tbody></table>
  <footer>Пазар — локална система за списъци за пазаруване и следене на разходите.</footer>
</div>
</body>
</html>
"""
