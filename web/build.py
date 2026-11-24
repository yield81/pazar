"""Сглобява web/index.html от template.html и examples/demo.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "template.html"
DEMO = ROOT / "examples" / "demo.json"
OUT = ROOT / "web" / "index.html"


def demo_data() -> dict:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    return {
        "stores": data["stores"],
        "products": [
            {
                "name": p["name"],
                "cat": p.get("category", ""),
                "unit": p.get("unit", "бр"),
                "kw": p.get("keywords", []),
                "prices": p.get("offers", []),
            }
            for p in data["products"]
        ],
    }


def main() -> int:
    payload = json.dumps(demo_data(), ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*DEMO*/" not in html:
        raise SystemExit("Липсва маркерът /*DEMO*/ в template.html")
    js = "const DEMO = " + payload + ";"
    OUT.write_text(html.replace("/*DEMO*/", js), encoding="utf-8")
    print(f"Готово: {OUT} ({OUT.stat().st_size} байта)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())