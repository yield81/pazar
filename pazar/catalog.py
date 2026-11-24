"""Магазини, продукти, цени, търсене и сравнение по магазини."""

from __future__ import annotations

from datetime import date

from . import textutil as tx
from .errors import PazarError
from .storage import DB, new_id


# ---------------------------------------------------------------- магазини

def find_store(db: DB, ref: str):
    """По id, после по точно име, после по частично име."""
    if not ref:
        return None
    ref = str(ref).strip()
    for store in db.stores:
        if store["id"] == ref:
            return store
    norm = tx.base_norm(ref)
    exact = [s for s in db.stores if tx.base_norm(s["name"]) == norm]
    if len(exact) == 1:
        return exact[0]
    partial = [s for s in db.stores if norm and norm in tx.base_norm(s["name"])]
    if len(partial) == 1:
        return partial[0]
    return None


def require_store(db: DB, ref: str):
    store = find_store(db, ref)
    if store:
        return store
    known = ", ".join(s["name"] for s in db.stores) or "няма"
    raise PazarError(f"Магазинът не е намерен: {ref}. Има: {known}")


def store_by_id(db: DB, store_id: str):
    for store in db.stores:
        if store["id"] == store_id:
            return store
    return None


def store_name(db: DB, store_id: str) -> str:
    store = store_by_id(db, store_id)
    return store["name"] if store else "Други"


def add_store(db: DB, name: str):
    name = (name or "").strip()
    if not name:
        raise PazarError("Името на магазина е празно.")
    for store in db.stores:
        if tx.base_norm(store["name"]) == tx.base_norm(name):
            return store, False
    store = {"id": new_id("s"), "name": name}
    db.stores.append(store)
    db.save_all()
    return store, True


# ---------------------------------------------------------------- продукти

def find_product(db: DB, ref: str):
    if not ref:
        return None
    ref = str(ref).strip()
    for product in db.products:
        if product["id"] == ref:
            return product
    norm = tx.base_norm(ref)
    exact = [p for p in db.products if tx.base_norm(p["name"]) == norm]
    if len(exact) == 1:
        return exact[0]
    scored = []
    for product in db.products:
        sc = tx.match_score(ref, product["name"], product.get("keywords"))
        if sc:
            scored.append((sc, product))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]["name"]))
    best = scored[0][0]
    top = [p for sc, p in scored if sc == best]
    return top[0] if len(top) == 1 else None


def add_product(db: DB, name: str, category: str = "", unit: str = "бр", keywords=()):
    name = (name or "").strip()
    if not name:
        raise PazarError("Името на продукта е празно.")
    for product in db.products:
        if tx.base_norm(product["name"]) == tx.base_norm(name):
            if category:
                product["category"] = category
            if keywords:
                product["keywords"] = sorted(set(product.get("keywords") or []) | set(keywords))
            db.save_all()
            return product, False
    product = {
        "id": new_id("p"),
        "name": name,
        "category": category or "Други",
        "unit": unit or "бр",
        "keywords": sorted(set(keywords or [])),
    }
    db.products.append(product)
    db.save_all()
    return product, True


def products_by_id(db: DB) -> dict:
    return {p["id"]: p for p in db.products}


# ---------------------------------------------------------------- цени

def offers_for(db: DB, product_id: str):
    """[(магазин, цена)] подредени по цена, най-напред най-евтиното."""
    out = []
    for offer in db.offers:
        if offer["product_id"] != product_id:
            continue
        store = store_by_id(db, offer["store_id"])
        if store:
            out.append((store, offer))
    out.sort(key=lambda t: (t[1]["price"], t[0]["name"]))
    return out


def set_offer(db: DB, product_ref: str, store_ref: str, price, when: str = None,
              source: str = "manual", note: str = ""):
    product = find_product(db, product_ref)
    if not product:
        raise PazarError(f"Продуктът не е намерен: {product_ref}. Добави го с: pazar product add {product_ref}")
    store = require_store(db, store_ref)
    try:
        value = round(float(tx.to_number(price)), 2)
    except (ValueError, TypeError):
        raise PazarError(f"Невалидна цена: {price}")
    if value < 0:
        raise PazarError("Цената не може да е отрицателна.")
    updated = when or date.today().isoformat()
    for offer in db.offers:
        if offer["product_id"] == product["id"] and offer["store_id"] == store["id"]:
            offer.update(price=value, updated=updated, source=source, note=note or offer.get("note", ""))
            db.save_all()
            return offer
    offer = {
        "product_id": product["id"],
        "store_id": store["id"],
        "price": value,
        "updated": updated,
        "source": source,
        "note": note,
    }
    db.offers.append(offer)
    db.save_all()
    return offer


def delete_offer(db: DB, product_ref: str, store_ref: str) -> None:
    product = find_product(db, product_ref)
    store = require_store(db, store_ref)
    if not product:
        raise PazarError(f"Продуктът не е намерен: {product_ref}")
    before = len(db.offers)
    db.offers = [
        o for o in db.offers
        if not (o["product_id"] == product["id"] and o["store_id"] == store["id"])
    ]
    if len(db.offers) == before:
        raise PazarError(f"Няма цена на {product['name']} в {store['name']}.")
    db.save_all()


def uses_example_data(offers) -> bool:
    return any(o.get("source") == "example" for _s, o in offers)


# ---------------------------------------------------------------- търсене

def suggestions(db: DB, ref: str, threshold: int = 70, limit: int = 3) -> list:
    """Близки продукти при нееднозначно или непознато име."""
    scored = []
    for product in db.products:
        sc = tx.match_score(ref, product["name"], product.get("keywords"))
        if sc >= threshold:
            scored.append((sc, product))
    scored.sort(key=lambda t: (-t[0], len(t[1]["name"]), t[1]["name"]))
    return [p for _sc, p in scored[:limit]]


def search(db: DB, query: str, limit: int = 20):
    """[(продукт, оферти)] подредени по релевантност."""
    scored = []
    for product in db.products:
        sc = tx.match_score(query, product["name"], product.get("keywords"))
        if sc:
            scored.append((sc, product))
    scored.sort(key=lambda t: (-t[0], tx.base_norm(t[1]["name"])))
    return [(p, offers_for(db, p["id"])) for _sc, p in scored[:limit]]


def compare(db: DB, items):
    """
    items: [{"name": str, "qty": float, "product_id": str|None}]
    Връща поименни оферти + план по магазини (най-евтино) + вариант с едно място.
    """
    results = []
    for raw in items:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        qty = float(raw.get("qty") or 1)
        product = None
        if raw.get("product_id"):
            product = next((p for p in db.products if p["id"] == raw["product_id"]), None)
        if product is None:
            product = find_product(db, name)
        offers = offers_for(db, product["id"]) if product else []
        results.append({
            "name": product["name"] if product else name,
            "qty": qty,
            "product": product,
            "offers": offers,
            "cheapest": offers[0] if offers else None,
        })

    split_total = 0.0
    by_store: dict = {}
    missing = []
    for res in results:
        if not res["cheapest"]:
            missing.append(res["name"])
            continue
        store, offer = res["cheapest"]
        line = round(offer["price"] * res["qty"], 2)
        split_total += line
        bucket = by_store.setdefault(store["id"], {"store": store, "total": 0.0, "items": []})
        bucket["total"] = round(bucket["total"] + line, 2)
        bucket["items"].append({"name": res["name"], "qty": res["qty"], "total": line,
                                "price": offer["price"]})

    # Най-евтин магазин, в който се намира всичко.
    store_totals: dict = {}
    for res in results:
        for store, offer in res["offers"]:
            bucket = store_totals.setdefault(store["id"], {"store": store, "total": 0.0, "covered": 0})
            bucket["total"] = round(bucket["total"] + offer["price"] * res["qty"], 2)
            bucket["covered"] += 1
    complete = [b for b in store_totals.values() if b["covered"] == len(results) and results]
    single = min(complete, key=lambda b: b["total"]) if complete else None
    if single is None and store_totals:
        best = max(store_totals.values(), key=lambda b: (b["covered"], -b["total"]))
        single = dict(best)
        single["complete"] = False
    if single is not None:
        single.setdefault("complete", True)

    return {
        "results": results,
        "split_total": round(split_total, 2),
        "by_store": sorted(by_store.values(), key=lambda b: b["total"]),
        "single": single,
        "missing": missing,
        "count": len(results),
    }
