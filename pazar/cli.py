"""Команден интерфейс: python3 -m pazar <команда>."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import __version__, catalog, report as report_mod, shopping, textutil as tx
from .errors import PazarError
from .storage import DB

EXAMPLE_NOTE = (
    "⚠ Цените са примерни данни — замени ги с реални: "
    "pazar price set ПРОДУКТ МАГАЗИН ЦЕНА"
)


def _warn_example(flag: bool) -> None:
    if flag:
        print(EXAMPLE_NOTE)


def _table(headers, rows, right=()):
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = []
    out.append("  ".join(str(h).ljust(widths[i]) if i not in right else str(h).rjust(widths[i])
                         for i, h in enumerate(headers)))
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) if i not in right else str(c).rjust(widths[i])
                             for i, c in enumerate(row)))
    return "\n".join(out)


def _read_item_file(path: str) -> list:
    target = Path(path)
    if not target.exists():
        raise PazarError(f"Файлът не е намерен: {path}")
    items = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, qty = tx.parse_qty_spec(line)
        for sep in (";", "\t", "|"):
            if sep in name:
                head, _mid, tail = name.partition(sep)
                if tail.strip():
                    try:
                        qty = float(tx.to_number(tail))
                        name = head.strip()
                    except ValueError:
                        pass
                break
        if name:
            items.append({"name": name, "qty": qty})
    if not items:
        raise PazarError(f"Файлът {path} не съдържа позиции.")
    return items


def _validate_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value or ""):
        raise PazarError(f"Месецът се задава като ГГГГ-ММ, получено: {value}")
    return value


# ------------------------------------------------------------------ основни

def cmd_init(args):
    db = DB()
    print(f"Папка с данни: {db.root}")
    print(f"Магазини: {len(db.stores)}   Продукти: {len(db.products)}   Цени: {len(db.offers)}   "
          f"Списъци: {len(db.lists)}   Покупки: {len(db.purchases)}")
    if not db.stores:
        print("Съвет: `pazar demo` зарежда примерни данни, `pazar store add ИМЕ` добавя магазин.")
    return 0


def cmd_demo(args):
    db = DB()
    if args.clear:
        db.reset()
        print("Старите данни са изтрити.")
    path = Path(__file__).resolve().parent.parent / "examples" / "demo.json"
    if not path.exists():
        raise PazarError(f"Липсва примерният файл: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    stores = products = offers = 0
    for entry in data.get("stores", []):
        _store, created = catalog.add_store(db, entry["name"] if isinstance(entry, dict) else entry)
        stores += int(created)
    for entry in data.get("products", []):
        product, created = catalog.add_product(
            db, entry["name"], entry.get("category", ""), entry.get("unit", "бр"),
            entry.get("keywords", []),
        )
        products += int(created)
        for offer in entry.get("offers", []):
            store_name, price = offer[0], offer[1]
            catalog.set_offer(db, product["id"], store_name, price,
                              source="example", note="примерна цена")
            offers += 1
    print(f"Заредени: {stores} нови магазина, {products} нови продукта, {offers} цени.")
    print("Всички цени са ОБОЗНАЧЕНИ като примерни (source=example).")
    return 0


# ------------------------------------------------------------------ магазини

def cmd_store_add(args):
    db = DB()
    name = " ".join(args.name).strip()
    store, created = catalog.add_store(db, name)
    print(("Добавен магазин" if created else "Магазинът вече съществува") + f": {store['name']} ({store['id']})")
    return 0


def cmd_store_ls(args):
    db = DB()
    if not db.stores:
        print("Няма магазини. Добави с: pazar store add ИМЕ")
        return 0
    rows = []
    for store in db.stores:
        count = sum(1 for o in db.offers if o["store_id"] == store["id"])
        rows.append([store["name"], store["id"], count])
    print(_table(["Магазин", "ID", "Цени"], rows, right=(2,)))
    return 0


# ------------------------------------------------------------------ продукти

def cmd_product_add(args):
    db = DB()
    name = " ".join(args.name).strip()
    product, created = catalog.add_product(db, name, args.cat, args.unit, args.kw or ())
    state = "Добавен продукт" if created else "Продуктът вече съществува — обновен"
    print(f"{state}: {product['name']} [{product['category']}] ({product['id']})")
    return 0


def cmd_product_ls(args):
    db = DB()
    if not db.products:
        print("Няма продукти. Добави с: pazar product add ИМЕ")
        return 0
    rows = []
    for product in sorted(db.products, key=lambda p: (p.get("category", ""), p["name"])):
        offers = catalog.offers_for(db, product["id"])
        best = tx.money(offers[0][1]["price"]) if offers else "—"
        rows.append([product["name"], product.get("category", ""), product.get("unit", "бр"),
                     len(offers), best])
    print(_table(["Продукт", "Категория", "Ед.", "Цени", "Най-евтино"], rows, right=(3, 4)))
    return 0


# ------------------------------------------------------------------ цени

def cmd_price_set(args):
    db = DB()
    offer = catalog.set_offer(db, args.product, args.store, args.price,
                              when=args.date, note=args.note or "")
    product = catalog.find_product(db, args.product)
    print(f"Цена записана: {product['name']} — "
          f"{catalog.store_name(db, offer['store_id'])} = {tx.money(offer['price'])} "
          f"({offer['updated']})")
    if offer.get("source") == "example":
        print("Заместваш примерна цена с реална — добре дошло.")
    return 0


def cmd_price_ls(args):
    db = DB()
    rows = []
    example = False
    for offer in sorted(db.offers, key=lambda o: (o["product_id"], o["price"])):
        product = next((p for p in db.products if p["id"] == offer["product_id"]), None)
        if args.product:
            sc = tx.match_score(args.product, (product or {}).get("name", ""),
                                (product or {}).get("keywords"))
            if not sc:
                continue
        example = example or offer.get("source") == "example"
        rows.append([(product or {}).get("name", "?"),
                     catalog.store_name(db, offer["store_id"]),
                     tx.money(offer["price"]), offer.get("updated", ""),
                     "примерна" if offer.get("source") == "example" else "реална"])
    if not rows:
        print("Няма записани цени.")
        return 0
    print(_table(["Продукт", "Магазин", "Цена", "Обновена", "Източник"], rows, right=(2,)))
    _warn_example(example)
    return 0


def cmd_price_del(args):
    db = DB()
    catalog.delete_offer(db, args.product, args.store)
    print(f"Цената е премахната: {args.product} / {args.store}")
    return 0


# ------------------------------------------------------------------ търсене

def cmd_search(args):
    db = DB()
    query = " ".join(args.query).strip()
    results = catalog.search(db, query)
    if not results:
        print(f"Няма съвпадения за „{query}“.")
        if db.products:
            print("Добре дошли са близки имена или нов продукт: "
                  f"pazar product add \"{query}\"")
        else:
            print("Каталогът е празен — зареди примерни данни с `pazar demo`.")
        return 0
    print(f"Търсене: {query} — {len(results)} резултата")
    example = False
    for index, (product, offers) in enumerate(results, 1):
        print(f"\n{index}. {product['name']}  [{product.get('category', 'Други')}]")
        if not offers:
            print("     няма записани цени")
            continue
        for store, offer in offers[:5]:
            mark = "▶" if (store, offer) == offers[0] else " "
            example = example or offer.get("source") == "example"
            print(f"     {mark} {store['name']:<14} {tx.money(offer['price']):>9}   {offer.get('updated', '')}")
        if len(offers) > 5:
            print(f"     … и още {len(offers) - 5} магазина")
    _warn_example(example)
    return 0


def cmd_compare(args):
    db = DB()
    items = list(args.items or [])
    if args.file:
        items.extend(_read_item_file(args.file))
    if not items:
        raise PazarError("Посочи продукти: pazar compare мляко хляб яйца  (или --file списък.txt)")
    if args.qty is not None:
        parsed = [{"name": tx.parse_qty_spec(i)[0], "qty": args.qty} for i in items]
    else:
        parsed = [{"name": name, "qty": qty} for name, qty in (tx.parse_qty_spec(i) for i in items)]
    result = catalog.compare(db, parsed)

    print(f"Сравнение на {result['count']} продукта в {len(db.stores)} магазина")
    example = False
    for entry in result["results"]:
        qty = tx.qty(entry["qty"])
        suffix = f"  x{qty}" if entry["qty"] != 1 else ""
        print(f"\n• {entry['name']}{suffix}")
        if not entry["offers"]:
            print("    няма записана цена")
            continue
        for store, offer in entry["offers"][:6]:
            mark = "▶" if (store, offer) == entry["offers"][0] else " "
            example = example or offer.get("source") == "example"
            line_total = offer["price"] * entry["qty"]
            total_part = f"= {tx.money(line_total)}" if entry["qty"] != 1 else ""
            print(f"    {mark} {store['name']:<14} {tx.money(offer['price']):>9} "
                  f"{total_part}"
                  f"   {offer.get('updated', '')}")

    print("\n" + "-" * 46)
    if result["by_store"]:
        print(f"Най-евтино общо (разпределено): {tx.money(result['split_total'])}")
        for bucket in result["by_store"]:
            print(f"  {bucket['store']['name']:<16} {tx.money(bucket['total']):>9}   "
                  f"{len(bucket['items'])} поз.")
    single = result["single"]
    if single:
        note = "" if single.get("complete", True) else "  (не всичко се намира там)"
        print(f"Всичко от един магазин: {single['store']['name']} — "
              f"{tx.money(single['total'])}{note}")
    if result["missing"]:
        print(f"Без цена: {', '.join(result['missing'])}")
    _warn_example(example)
    return 0


# ------------------------------------------------------------------ списъци

def _resolve_list_ref(args) -> str | None:
    return getattr(args, "list", None)


def cmd_list_new(args):
    db = DB()
    lst = shopping.new_list(db, args.name)
    print(f"Създаден списък: {lst['name']} ({lst['id']})")
    return 0


def cmd_list_ls(args):
    db = DB()
    if not db.lists:
        print("Няма списъци. Създай с: pazar list new ИМЕ")
        return 0
    status_bg = {"active": "активен", "done": "завършен", "close": "затворен"}
    rows = []
    for lst in db.lists:
        bought = sum(1 for i in lst["items"] if i.get("bought"))
        totals = shopping.list_totals(db, lst)
        rows.append([lst["name"], lst["id"],
                     status_bg.get(lst.get("status"), lst.get("status")),
                     f"{bought}/{len(lst['items'])}",
                     tx.money(totals["total"]), lst.get("created", "")])
    print(_table(["Списък", "ID", "Статус", "Купени", "Оценка", "Създаден"], rows, right=(4,)))
    return 0


def cmd_list_show(args):
    db = DB()
    lst = shopping.get_list(db, _resolve_list_ref(args))
    status_bg = {"active": "активен", "done": "завършен", "close": "затворен"}
    print(f"Списък: {lst['name']}  ({lst['id']}) — {status_bg.get(lst.get('status'), '?')}")
    if not lst["items"]:
        print("  (празен)")
        return 0

    groups: dict = {}
    for item in lst["items"]:
        groups.setdefault(item.get("store_id"), []).append(item)

    example = False
    def sort_key(store_id):
        return catalog.store_name(db, store_id) if store_id else "zzz"

    for store_id in sorted(groups, key=sort_key):
        items = groups[store_id]
        store_name = catalog.store_name(db, store_id) if store_id else "Без магазин"
        subtotal = 0.0
        for item in items:
            if item.get("bought"):
                continue
            price, _sid = shopping.estimate(db, item)
            if price is not None:
                subtotal += price * float(item["qty"])
            example = example or bool(item.get("product_id")) and any(
                o.get("source") == "example"
                for o in db.offers if o["product_id"] == item.get("product_id"))
        print(f"\n{store_name} — {len(items)} поз., ~{tx.money(subtotal)}")
        for item in items:
            index = lst["items"].index(item) + 1
            mark = "x" if item.get("bought") else " "
            line = f"  [{mark}] {index:>2}. {item['name']}  x{tx.qty(item['qty'])} {item.get('unit', 'бр')}"
            if item.get("bought"):
                line += f"   купено {tx.money(item.get('spent') or 0)}"
            else:
                price, _sid = shopping.estimate(db, item)
                if price is None:
                    line += "   (няма цена)"
                else:
                    line += f"   ~{tx.money(price)}/бр = {tx.money(price * float(item['qty']))}"
            print(line)

    totals = shopping.list_totals(db, lst)
    print()
    print(f"Оценена сума за покупка: {tx.money(totals['total'])} "
          f"({totals['pending']} поз. за покупка)")
    if totals["by_store"]:
        parts = ", ".join(f"{catalog.store_name(db, b['store_id'])} {tx.money(b['total'])}"
                          for b in totals["by_store"])
        print(f"По магазини: {parts}")
    if totals["missing"]:
        print(f"Без цена: {', '.join(i['name'] for i in totals['missing'])}")
    _warn_example(example)
    return 0


def cmd_list_add(args):
    db = DB()
    lst, added, merged = shopping.add_items(
        db, _resolve_list_ref(args), args.items, qty=args.qty,
        store_ref=args.store, note=args.note or "",
    )
    print(f"Списък: {lst['name']}")
    for item in added:
        where = f" → {catalog.store_name(db, item['store_id'])}" if item.get("store_id") else ""
        print(f"  + {item['name']} x{tx.qty(item['qty'])}{where}")
        if not item.get("product_id"):
            near = catalog.suggestions(db, item["name"])
            if near:
                names = ", ".join(p["name"] for p in near)
                print(f"    вж. възможни съвпадения: {names} — "
                      f"добавено без връзка към цена.")
    for item in merged:
        print(f"  ~ {item['name']} вече беше в списъка, сега x{tx.qty(item['qty'])}")
    return 0


def cmd_list_rm(args):
    db = DB()
    removed = shopping.remove_items(db, _resolve_list_ref(args), args.items)
    for name in removed:
        print(f"  − {name}")
    return 0


def cmd_list_plan(args):
    db = DB()
    changed = shopping.plan_stores(db, _resolve_list_ref(args))
    print(f"Разпределението е обновено — променени позиции: {changed}")
    return 0


def cmd_list_store(args):
    db = DB()
    count = shopping.set_item_store(db, _resolve_list_ref(args), args.items, args.store)
    print(f"Преместени {count} поз. в {catalog.require_store(db, args.store)['name']}")
    return 0


def cmd_list_export(args):
    db = DB()
    path = args.file or f"prices-{date.today().isoformat()}.csv"
    out = shopping.export_prices(db, _resolve_list_ref(args), path)
    print(f"Шаблон с цени: {out}")
    print("Попълни колона unit_price и записвай с: pazar buy --file", out)
    return 0


def cmd_list_close(args):
    db = DB()
    lst = shopping.get_list(db, _resolve_list_ref(args))
    lst["status"] = "close"
    db.save_all()
    print(f"Списъкът „{lst['name']}“ е затворен (без записана покупка).")
    return 0


def cmd_list_reopen(args):
    db = DB()
    lst = next((l for l in db.lists if l["id"] == args.id), None)
    if not lst:
        raise PazarError(f"Списъкът не е намерен: {args.id}")
    lst["status"] = "active"
    lst.pop("closed", None)
    db.save_all()
    print(f"Списъкът „{lst['name']}“ е отново активен.")
    return 0


def cmd_list_del(args):
    db = DB()
    lst = next((l for l in db.lists if l["id"] == args.id), None)
    if not lst:
        raise PazarError(f"Списъкът не е намерен: {args.id}")
    db.lists.remove(lst)
    db.save_all()
    print(f"Изтрит списък: {lst['name']} ({lst['id']}). Записаните покупки остават.")
    return 0


# ------------------------------------------------------------------ покупки

def cmd_buy(args):
    db = DB()
    lst = shopping.get_list(db, _resolve_list_ref(args))
    created = shopping.record_purchase(
        db, lst["id"], store_ref=args.store, price_args=args.price or (),
        file_path=args.file, use_estimates=args.use_estimates, when=args.date,
        note=args.note or "", reassign=args.reassign,
    )
    for purchase in created:
        print(f"Записана покупка {purchase['id']}: "
              f"{catalog.store_name(db, purchase['store_id'])} · {purchase['date']} · "
              f"{len(purchase['items'])} поз. · {tx.money(purchase['total'])}")
    print(f"Общо записано: {tx.money(sum(p['total'] for p in created))}")

    pending = [i for i in lst["items"] if not i.get("bought")]
    if pending:
        print(f"Остават {len(pending)} поз.: " + ", ".join(i["name"] for i in pending))
    else:
        print(f"Списъкът „{lst['name']}“ е напълно закупен.")
    return 0


def cmd_purchase_ls(args):
    db = DB()
    purchases = sorted(db.purchases, key=lambda p: p["date"], reverse=True)
    if args.month:
        month = _validate_month(args.month)
        purchases = [p for p in purchases if p["date"][:7] == month]
    if not purchases:
        print("Няма записани покупки.")
        return 0
    rows = []
    for purchase in purchases:
        rows.append([purchase["date"], catalog.store_name(db, purchase.get("store_id")),
                     len(purchase.get("items", [])), tx.money(purchase["total"]),
                     purchase["id"]])
    print(_table(["Дата", "Магазин", "Поз.", "Сума", "ID"], rows, right=(2, 3)))
    print(f"Общо: {tx.money(sum(p['total'] for p in purchases))}")
    return 0


def cmd_purchase_show(args):
    db = DB()
    purchase = next((p for p in db.purchases if p["id"] == args.id), None)
    if not purchase:
        raise PazarError(f"Покупката не е намерена: {args.id}")
    print(f"Покупка {purchase['id']} · {purchase['date']} · "
          f"{catalog.store_name(db, purchase.get('store_id'))}")
    for line in purchase.get("items", []):
        print(f"  {line['name']}  x{tx.qty(line['qty'])} "
              f"@ {tx.money(line['unit_price'])} = {tx.money(line['total'])}")
    print(f"Общо: {tx.money(purchase['total'])}")
    if purchase.get("list_name"):
        print(f"От списък: {purchase['list_name']}")
    if purchase.get("note"):
        print(f"Бележка: {purchase['note']}")
    return 0


def cmd_purchase_del(args):
    db = DB()
    purchase = shopping.delete_purchase(db, args.id)
    print(f"Изтрита покупка {purchase['id']} на {tx.money(purchase['total'])} "
          f"— позициите са върнати като непокупени.")
    return 0


# ------------------------------------------------------------------ отчети

def cmd_report(args):
    db = DB()
    month = _validate_month(args.month) if args.month else None
    if not month and not args.all and args.year is None:
        month = date.today().strftime("%Y-%m")
    if month and args.year:
        raise PazarError("Посочи или --month, или --year, или --all.")
    rep = report_mod.collect(db, month=month, year=args.year)
    print(report_mod.format_text(rep))
    if args.html:
        target = Path(args.html)
        target.write_text(report_mod.format_html(rep), encoding="utf-8")
        print(f"\nHTML отчет: {target.resolve()}")
    return 0


def cmd_budget_show(args):
    db = DB()
    value = db.settings.get("budget_month")
    spent = 0.0
    month = date.today().strftime("%Y-%m")
    for purchase in db.purchases:
        if purchase["date"][:7] == month:
            spent += float(purchase["total"])
    if value:
        value = float(value)
        print(f"Бюджет за месеца: {tx.money(value)}")
        print(f"Похарчено този месец ({month}): {tx.money(spent)} "
              f"({spent / value * 100:.1f}%), остават {tx.money(value - spent)}")
    else:
        print(f"Няма зададен бюджет. Похарчено този месец ({month}): {tx.money(spent)}")
        print("Задай с: pazar budget set 400")
    return 0


def cmd_budget_set(args):
    db = DB()
    try:
        value = round(float(tx.to_number(args.amount)), 2)
    except ValueError:
        raise PazarError(f"Невалидна сума: {args.amount}")
    if value <= 0:
        raise PazarError("Бюджетът трябва да е положително число.")
    db.settings["budget_month"] = value
    db.save_all()
    print(f"Месечен бюджет: {tx.money(value)}")
    return 0


# ------------------------------------------------------------------ парсер

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pazar",
        description="Търсене на продукти по магазини, списъци за пазаруване и следене на разходи.",
    )
    parser.add_argument("--version", action="version", version=f"pazar {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="показва състоянието на данните")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("demo", help="зарежда примерни данни (магазини, продукти, цени)")
    p.add_argument("--clear", action="store_true", help="първо изтрий всички текущи данни")
    p.set_defaults(func=cmd_demo)

    # магазини
    p = sub.add_parser("store", help="магазини")
    ssub = p.add_subparsers(dest="sub", required=True)
    a = ssub.add_parser("add", help="добави магазин")
    a.add_argument("name", nargs="+", help="име на магазина")
    a.set_defaults(func=cmd_store_add)
    a = ssub.add_parser("ls", help="списък на магазините")
    a.set_defaults(func=cmd_store_ls)

    # продукти
    p = sub.add_parser("product", help="продукти")
    ssub = p.add_subparsers(dest="sub", required=True)
    a = ssub.add_parser("add", help="добави продукт")
    a.add_argument("name", nargs="+", help="име на продукта")
    a.add_argument("--cat", default="", help="категория, напр. Млечни")
    a.add_argument("--unit", default="бр", help="мерна единица: бр, кг, л …")
    a.add_argument("--kw", nargs="*", default=[], help="допълнителни ключови думи за търсене")
    a.set_defaults(func=cmd_product_add)
    a = ssub.add_parser("ls", help="списък на продуктите")
    a.set_defaults(func=cmd_product_ls)

    # цени
    p = sub.add_parser("price", help="цени по магазини")
    ssub = p.add_subparsers(dest="sub", required=True)
    a = ssub.add_parser("set", help="запиши цена")
    a.add_argument("product", help="продукт (име или ID)")
    a.add_argument("store", help="магазин (име или ID)")
    a.add_argument("price", help="цена, напр. 2.49")
    a.add_argument("--date", default=None, help="дата ГГГГ-ММ-ДД")
    a.add_argument("--note", default="", help="бележка, напр. промоция")
    a.set_defaults(func=cmd_price_set)
    a = ssub.add_parser("ls", help="всички записани цени")
    a.add_argument("product", nargs="?", help="филтър по продукт")
    a.set_defaults(func=cmd_price_ls)
    a = ssub.add_parser("del", help="премахни цена")
    a.add_argument("product", help="продукт")
    a.add_argument("store", help="магазин")
    a.set_defaults(func=cmd_price_del)

    # търсене
    p = sub.add_parser("search", help="търси продукт и показва цените по магазини")
    p.add_argument("query", nargs="+", help="думи за търсене")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("compare", help="сравни списък продукти между магазините")
    p.add_argument("items", nargs="*", help="продукти, напр. мляко хляб яйца*2")
    p.add_argument("--file", help="файл с по един продукт на ред (продукт;количество)")
    p.add_argument("--qty", type=float, help="количество за всички позиции")
    p.set_defaults(func=cmd_compare)

    # списъци
    p = sub.add_parser("list", help="списъци за пазаруване")
    ssub = p.add_subparsers(dest="sub", required=True)

    a = ssub.add_parser("new", help="създай списък")
    a.add_argument("name", help="име на списъка")
    a.set_defaults(func=cmd_list_new)

    a = ssub.add_parser("ls", help="всички списъци")
    a.set_defaults(func=cmd_list_ls)

    a = ssub.add_parser("show", help="покажи списъка, групиран по магазин")
    a.add_argument("list", nargs="?", help="ID или име на списъка")
    a.set_defaults(func=cmd_list_show)

    a = ssub.add_parser("add", help="добави позиции")
    a.add_argument("items", nargs="+", help="продукти, напр. мляко*2 хляб")
    a.add_argument("--list", help="списък (по подразбиране: активният)")
    a.add_argument("--qty", type=float, help="количество за всички")
    a.add_argument("--store", help="магазин, в който ще се купува")
    a.add_argument("--note", default="", help="бележка")
    a.set_defaults(func=cmd_list_add)

    a = ssub.add_parser("rm", help="махни позиции")
    a.add_argument("items", nargs="+", help="имена или номера на позиции")
    a.add_argument("--list", help="списък (по подразбиране: активният)")
    a.set_defaults(func=cmd_list_rm)

    a = ssub.add_parser("plan", help="разпредели позициите към най-евтините магазини")
    a.add_argument("list", nargs="?", help="ID или име на списъка")
    a.set_defaults(func=cmd_list_plan)

    a = ssub.add_parser("store", help="премести позиции в друг магазин")
    a.add_argument("items", nargs="+", help="имена или номера на позиции")
    a.add_argument("--store", required=True, help="целеви магазин")
    a.add_argument("--list", help="списък (по подразбиране: активният)")
    a.set_defaults(func=cmd_list_store)

    a = ssub.add_parser("export", help="изнеси шаблон с цени за попълване")
    a.add_argument("list", nargs="?", help="ID или име на списъка")
    a.add_argument("--file", help="куде да се запише CSV-то")
    a.set_defaults(func=cmd_list_export)

    a = ssub.add_parser("close", help="затвори списък без покупка")
    a.add_argument("list", nargs="?", help="ID или име на списъка")
    a.set_defaults(func=cmd_list_close)

    a = ssub.add_parser("reopen", help="отвори отново затворен списък")
    a.add_argument("id", help="ID на списъка")
    a.set_defaults(func=cmd_list_reopen)

    a = ssub.add_parser("del", help="изтрий списък (покупките остават)")
    a.add_argument("id", help="ID на списъка")
    a.set_defaults(func=cmd_list_del)

    # покупки
    p = sub.add_parser("buy", help="запиши реална покупка от списък")
    p.add_argument("list", nargs="?", help="списък (по подразбиране: активният)")
    p.add_argument("--store", help="магазин (позициите, планирани за него)")
    p.add_argument("--price", action="append", metavar="ИМЕ=ЦЕНА",
                   help="реална цена на позиция (повтаря се)")
    p.add_argument("--file", help="CSV с колони name,unit_price[,store][,qty]")
    p.add_argument("--use-estimates", action="store_true",
                   help="ползвай цените от каталога за позиции без посочена цена")
    p.add_argument("--reassign", action="store_true",
                   help="със --store: запиши всички оставащи позиции в този магазин")
    p.add_argument("--date", help="дата на покупката ГГГГ-ММ-ДД")
    p.add_argument("--note", default="", help="бележка")
    p.set_defaults(func=cmd_buy)

    p = sub.add_parser("purchase", help="записани покупки")
    ssub = p.add_subparsers(dest="sub", required=True)
    a = ssub.add_parser("ls", help="списък на покупките")
    a.add_argument("--month", help="филтър ГГГГ-ММ")
    a.set_defaults(func=cmd_purchase_ls)
    a = ssub.add_parser("show", help="подробности за покупка")
    a.add_argument("id", help="ID на покупката")
    a.set_defaults(func=cmd_purchase_show)
    a = ssub.add_parser("del", help="изтрий покупка")
    a.add_argument("id", help="ID на покупката")
    a.set_defaults(func=cmd_purchase_del)

    # отчети
    p = sub.add_parser("report", help="отчет за разходите")
    p.add_argument("--month", help="месец ГГГГ-ММ (по подразбиране: текущият)")
    p.add_argument("--year", type=int, help="година, напр. 2026")
    p.add_argument("--all", action="store_true", help="всички периоди")
    p.add_argument("--html", help="запиши и HTML отчет в този файл")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("budget", help="месечен бюджет")
    ssub = p.add_subparsers(dest="sub", required=True)
    a = ssub.add_parser("show", help="покажи бюджета и разходите досега")
    a.set_defaults(func=cmd_budget_show)
    a = ssub.add_parser("set", help="задай месечен бюджет")
    a.add_argument("amount", help="сума, напр. 400")
    a.set_defaults(func=cmd_budget_set)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except PazarError as exc:
        print(f"Грешка: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
