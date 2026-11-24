"""Списъци за пазаруване, шаблони с цени и запис на реални покупки."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from . import catalog, textutil as tx
from .errors import PazarError
from .storage import DB, new_id


# ---------------------------------------------------------------- списъци

def get_list(db: DB, ref=None):
    if ref is None:
        active = [l for l in db.lists if l.get("status") == "active"]
        if not active:
            raise PazarError(
                "Няма активен списък. Създай нов с: pazar list new ИМЕ "
                "или посочи съществуващ с: pazar list show ID (виж pazar list ls)."
            )
        if len(active) > 1:
            names = ", ".join(f"{l['name']} ({l['id']})" for l in active)
            raise PazarError(f"Има няколко активни списъка: {names}. Посочи кой с `pazar list show ID`.")
        return active[0]
    ref = str(ref).strip()
    for lst in db.lists:
        if lst["id"] == ref:
            return lst
    norm = tx.base_norm(ref)
    matches = [l for l in db.lists if tx.base_norm(l["name"]) == norm]
    if len(matches) == 1:
        return matches[0]
    raise PazarError(f"Списъкът не е намерен: {ref}")


def new_list(db: DB, name: str):
    name = (name or "").strip()
    if not name:
        raise PazarError("Името на списъка е празно.")
    lst = {"id": new_id("l"), "name": name, "created": date.today().isoformat(),
           "status": "active", "items": []}
    db.lists.append(lst)
    db.save_all()
    return lst


def estimate(db: DB, item):
    """(цена за бройка, магазин) за позицията или (None, магазин)."""
    if item.get("product_id"):
        offers = catalog.offers_for(db, item["product_id"])
        if offers:
            wanted = item.get("store_id")
            if wanted:
                for store, offer in offers:
                    if store["id"] == wanted:
                        return offer["price"], wanted
            store, offer = offers[0]
            return offer["price"], store["id"]
    return None, item.get("store_id")


def add_items(db: DB, ref, specs, qty=None, store_ref=None, note: str = ""):
    lst = get_list(db, ref)
    store = catalog.require_store(db, store_ref) if store_ref else None
    added, merged = [], []
    for spec in specs:
        name, spec_qty = tx.parse_qty_spec(spec)
        if not name:
            continue
        amount = float(qty) if qty is not None else spec_qty
        if amount <= 0:
            raise PazarError(f"Невалидно количество за {name}.")
        product = catalog.find_product(db, name)
        display = product["name"] if product else name
        store_id = store["id"] if store else None
        if store_id is None and product:
            offers = catalog.offers_for(db, product["id"])
            if offers:
                store_id = offers[0][0]["id"]
        existing = next((i for i in lst["items"]
                         if tx.base_norm(i["name"]) == tx.base_norm(display)), None)
        if existing:
            existing["qty"] = round(float(existing["qty"]) + amount, 2)
            if store_id and not existing.get("store_id"):
                existing["store_id"] = store_id
            merged.append(existing)
        else:
            item = {
                "id": new_id("i"),
                "name": display,
                "product_id": product["id"] if product else None,
                "qty": amount,
                "unit": product["unit"] if product else "бр",
                "store_id": store_id,
                "note": note or "",
                "bought": False,
            }
            lst["items"].append(item)
            added.append(item)
    if not added and not merged:
        raise PazarError("Нищо не е добавено — провери имената на продуктите.")
    db.save_all()
    return lst, added, merged


def remove_items(db: DB, ref, keys):
    lst = get_list(db, ref)
    removed = []
    for key in keys:
        item = _match_item(lst["items"], key)
        lst["items"].remove(item)
        removed.append(item["name"])
    db.save_all()
    return removed


def plan_stores(db: DB, ref) -> int:
    """Разпределя всяка позиция към магазина с най-евтена цена."""
    lst = get_list(db, ref)
    changed = 0
    for item in lst["items"]:
        if item.get("bought") or not item.get("product_id"):
            continue
        offers = catalog.offers_for(db, item["product_id"])
        if not offers:
            continue
        cheapest = offers[0][0]["id"]
        if item.get("store_id") != cheapest:
            item["store_id"] = cheapest
            changed += 1
    db.save_all()
    return changed


def set_item_store(db: DB, ref, keys, store_ref) -> int:
    lst = get_list(db, ref)
    store = catalog.require_store(db, store_ref)
    count = 0
    for key in keys:
        item = _match_item(lst["items"], key)
        item["store_id"] = store["id"]
        count += 1
    db.save_all()
    return count


def list_totals(db: DB, lst) -> dict:
    total = 0.0
    by_store: dict = {}
    missing = []
    bought_total = 0.0
    for item in lst["items"]:
        price, store_id = estimate(db, item)
        if item.get("bought"):
            bought_total += float(item.get("spent") or 0)
            continue
        if price is None:
            missing.append(item)
            continue
        line = round(price * float(item["qty"]), 2)
        total += line
        bucket = by_store.setdefault(store_id, {"store_id": store_id, "total": 0.0, "count": 0})
        bucket["total"] = round(bucket["total"] + line, 2)
        bucket["count"] += 1
    return {
        "total": round(total, 2),
        "by_store": sorted(by_store.values(), key=lambda b: -b["total"]),
        "missing": missing,
        "bought_total": round(bought_total, 2),
        "pending": sum(1 for i in lst["items"] if not i.get("bought")),
    }


def export_prices(db: DB, ref, path: str) -> str:
    lst = get_list(db, ref)
    target = Path(path)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "qty", "unit", "store", "estimate", "unit_price"])
        for item in lst["items"]:
            price, store_id = estimate(db, item)
            store_name = catalog.store_name(db, store_id) if store_id else ""
            writer.writerow([
                item["name"], tx.qty(item["qty"]), item["unit"], store_name,
                f"{price:.2f}" if price is not None else "", "",
            ])
    return str(target)


# ---------------------------------------------------------------- покупки

def _norm_header(value: str) -> str:
    return tx.base_norm(value).replace(" ", "_")


def read_price_file(path: str) -> list[dict]:
    target = Path(path)
    if not target.exists():
        raise PazarError(f"Файлът не е намерен: {path}")
    with target.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise PazarError("Файлът с цените е празен.")
        mapping = {_norm_header(h): h for h in reader.fieldnames if h}

        def col(*names):
            for name in names:
                if name in mapping:
                    return mapping[name]
            return None

        c_name = col("name", "продукт", "позиция", "item")
        c_price = col("unit_price", "price", "цена")
        c_qty = col("qty", "quantity", "количество")
        c_store = col("store", "магазин")
        if not c_name:
            raise PazarError("Липсва колона name (или „продукт“) във файла.")
        rows = []
        for line_no, row in enumerate(reader, start=2):
            name = (row.get(c_name) or "").strip()
            if not name:
                continue
            price = None
            if c_price and (row.get(c_price) or "").strip():
                try:
                    price = round(tx.to_number(row[c_price]), 2)
                except ValueError:
                    raise PazarError(f"Невалидна цена на ред {line_no}: {row.get(c_price)}")
            qty = None
            if c_qty and (row.get(c_qty) or "").strip():
                try:
                    qty = float(tx.to_number(row[c_qty]))
                except ValueError:
                    raise PazarError(f"Невалидно количество на ред {line_no}: {row.get(c_qty)}")
            store = (row.get(c_store) or "").strip() if c_store else ""
            rows.append({"name": name, "unit_price": price, "qty": qty, "store": store})
    if not rows:
        raise PazarError("Файлът не съдържа позиции.")
    return rows


def _match_item(items, key):
    key = str(key).strip()
    if key.isdigit():
        idx = int(key)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        raise PazarError(f"Няма позиция №{idx} в списъка.")
    norm = tx.base_norm(key)
    exact = [i for i in items if tx.base_norm(i["name"]) == norm]
    if len(exact) == 1:
        return exact[0]
    partial = [i for i in items if norm and norm in tx.base_norm(i["name"])]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise PazarError(f"Позицията не е в списъка: {key}")
    names = ", ".join(i["name"] for i in partial)
    raise PazarError(f"Несигурно съвпадение за „{key}“: {names}")


def _parse_price_args(price_args) -> dict:
    out = {}
    for arg in price_args or ():
        if "=" not in arg:
            raise PazarError(f"Цената се задава като „име=цена“, получено: {arg}")
        key, value = arg.rsplit("=", 1)
        try:
            out[key.strip()] = round(tx.to_number(value), 2)
        except ValueError:
            raise PazarError(f"Невалидна цена за {key}: {value}")
    return out


def record_purchase(db: DB, ref, store_ref=None, price_args=(), file_path=None,
                    use_estimates: bool = False, when: str = None, note: str = "",
                    reassign: bool = False):
    """
    Записва покупка/покупки и маркира позициите като купени.
    Без --store: всяка позиция се записва в нейния магазин (по един запис на магазин).
    Със --store X: записват се позициите, планирани за X (и непланираните).
    """
    lst = get_list(db, ref)
    when = when or date.today().isoformat()
    pending = [i for i in lst["items"] if not i.get("bought")]
    if not pending:
        raise PazarError("Всички позиции в списъка вече са купени.")

    store = None
    if store_ref:
        store = catalog.require_store(db, store_ref)
        if reassign:
            selected = list(pending)
        else:
            selected = [i for i in pending if i.get("store_id") in (None, store["id"])]
        if not selected:
            names = ", ".join(i["name"] for i in pending)
            raise PazarError(f"Няма позиции, планирани за {store['name']}. Остават: {names}")
    else:
        selected = list(pending)

    explicit = _parse_price_args(price_args)
    rows = read_price_file(file_path) if file_path else None

    plans = []  # (item, unit_price, store_id, qty)
    if rows is not None:
        for row in rows:
            item = _match_item(pending, row["name"])
            if item in [p[0] for p in plans]:
                raise PazarError(f"Позицията се повтаря във файла: {row['name']}")
            price = row["unit_price"]
            if price is None:
                price, _sid = estimate(db, item)
                if price is None:
                    raise PazarError(f"Липсва цена за {item['name']} — попълни unit_price във файла.")
            row_store = row.get("store") or ""
            if row_store:
                store_id = catalog.require_store(db, row_store)["id"]
            else:
                store_id = item.get("store_id") or (store["id"] if store else None)
            if not store_id:
                raise PazarError(f"Липсва магазин за {item['name']} — добави колона store или ползвай --store.")
            qty = row["qty"] or item["qty"]
            plans.append((item, float(price), store_id, float(qty)))
    else:
        for item in selected:
            price = None
            index = lst["items"].index(item) + 1
            for key, value in explicit.items():
                if key.isdigit():
                    if int(key) == index:
                        price = value
                        break
                elif tx.base_norm(key) == tx.base_norm(item["name"]):
                    price = value
                    break
            if price is None:
                for key, value in explicit.items():
                    if not key.isdigit() and tx.base_norm(key) in tx.base_norm(item["name"]):
                        price = value
                        break
            if price is None and use_estimates:
                price, _sid = estimate(db, item)
            if price is None:
                raise PazarError(
                    f"Липсва цена за „{item['name']}“ — добави --price \"{item['name']}=цена\" "
                    f"или --use-estimates."
                )
            store_id = item.get("store_id") or (store["id"] if store else None)
            if not store_id:
                raise PazarError(f"Липсва магазин за „{item['name']}“ — посочи --store.")
            qty = float(item["qty"])
            if reassign and store:
                store_id = store["id"]
            plans.append((item, float(price), store_id, qty))

    grouped: dict = {}
    for item, price, store_id, qty in plans:
        grouped.setdefault(store_id, []).append((item, price, qty))

    created = []
    for store_id, rows_ in grouped.items():
        lines = []
        total = 0.0
        for item, price, qty in rows_:
            line_total = round(price * qty, 2)
            total += line_total
            lines.append({
                "name": item["name"],
                "product_id": item.get("product_id"),
                "qty": qty,
                "unit": item.get("unit") or "бр",
                "unit_price": round(price, 2),
                "total": line_total,
            })
            item["bought"] = True
            item["spent"] = round(float(item.get("spent") or 0) + line_total, 2)
            item["bought_price"] = round(price, 2)
            item["store_id"] = store_id
        purchase = {
            "id": new_id("pu"),
            "date": when,
            "list_id": lst["id"],
            "list_name": lst["name"],
            "store_id": store_id,
            "items": lines,
            "total": round(total, 2),
            "currency": tx._CURRENCY,
            "note": note or "",
        }
        db.purchases.append(purchase)
        created.append(purchase)

    if all(i.get("bought") for i in lst["items"]):
        lst["status"] = "done"
        lst["closed"] = when
    db.save_all()
    return created


def delete_purchase(db: DB, purchase_id: str) -> dict:
    match = next((p for p in db.purchases if p["id"] == purchase_id), None)
    if not match:
        raise PazarError(f"Покупката не е намерена: {purchase_id}")
    lst = next((l for l in db.lists if l["id"] == match.get("list_id")), None)
    if lst:
        for item in lst["items"]:
            for line in match["items"]:
                if item["name"] == line["name"] and item.get("bought"):
                    item["bought"] = False
                    item["spent"] = round(float(item.get("spent") or 0) - line["total"], 2)
                    item.pop("bought_price", None)
        if lst.get("status") == "done":
            lst["status"] = "active"
            lst.pop("closed", None)
    db.purchases.remove(match)
    db.save_all()
    return match
