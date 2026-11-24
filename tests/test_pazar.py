"""Тестове на Пазар: търсене, сравнение, списъци, покупки, отчети и CLI."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from pazar import catalog, report, shopping
from pazar import textutil as tx
from pazar.cli import main
from pazar.errors import PazarError
from pazar.storage import DB


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_env = os.environ.get("PAZAR_DATA")
        os.environ["PAZAR_DATA"] = str(self.root)
        self.db = DB(self.root)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("PAZAR_DATA", None)
        else:
            os.environ["PAZAR_DATA"] = self._old_env
        self.tmp.cleanup()

    # --- помощници

    def fill(self):
        """Малък, напълно детерминистичен каталог."""
        for name in ("Лидл", "Кауфланд"):
            catalog.add_store(self.db, name)
        products = [
            ("Мляко 3% 1 л", "Млечни", "бр", ["мляко"],
             [("Лидл", "2.29"), ("Кауфланд", "2.45")]),
            ("Хляб бял 500 г", "Хлебни", "бр", ["хляб"],
             [("Лидл", "1.29"), ("Кауфланд", "1.39")]),
            ("Яйца 10 бр", "Млечни", "бр", ["яйца"],
             [("Кауфланд", "4.59")]),
        ]
        for name, cat, unit, kw, offers in products:
            product, _ = catalog.add_product(self.db, name, cat, unit, kw)
            for store, price in offers:
                catalog.set_offer(self.db, product["id"], store, price,
                                  source="example")

    def run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()


class TextutilTests(unittest.TestCase):
    def test_base_norm(self):
        self.assertEqual(tx.base_norm("  Мляко__3.5%  "), "мляко 3 5")

    def test_variants_adds_forms(self):
        self.assertIn("мляко", tx.variants("Мляко"))
        # латиницата се опростява до същия ключ
        self.assertEqual(tx.loose("мляко"), tx.loose("mljako"))
        self.assertEqual(tx.loose("мляко"), tx.loose("mlako"))

    def test_match_score(self):
        self.assertEqual(tx.match_score("мляко", "Мляко 3% 1 л"), 80)
        self.assertEqual(tx.match_score("мляко", "Мляко"), 100)
        self.assertEqual(tx.match_score("мляко", "Хляб бял"), 0)
        self.assertGreater(tx.match_score("мляко", "Мляко 3% 1 л"),
                           tx.match_score("мля", "Кашкавал"))
        self.assertGreater(tx.match_score("mljako", "Мляко 3% 1 л"), 0)

    def test_match_keywords(self):
        self.assertGreater(tx.match_score("йогурт", "Кисело мляко 400 г", ["йогурт"]), 0)

    def test_parse_qty_spec(self):
        self.assertEqual(tx.parse_qty_spec("мляко*2"), ("мляко", 2.0))
        self.assertEqual(tx.parse_qty_spec("мляко x 1,5"), ("мляко", 1.5))
        self.assertEqual(tx.parse_qty_spec("мляко"), ("мляко", 1.0))

    def test_numbers_and_money(self):
        self.assertEqual(tx.to_number("2,49"), 2.49)
        self.assertEqual(tx.to_number("2.49 лв"), 2.49)
        self.assertEqual(tx.money(2.5), "2.50 лв")
        self.assertEqual(tx.qty(2.0), "2")
        self.assertEqual(tx.qty(1.5), "1.5")


class CatalogTests(Base):
    def test_add_store_is_idempotent(self):
        first, created = catalog.add_store(self.db, "Лидл")
        self.assertTrue(created)
        second, created_again = catalog.add_store(self.db, "  лидл ")
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])

    def test_add_product_is_idempotent(self):
        product, created = catalog.add_product(self.db, "Мляко", "Млечни")
        self.assertTrue(created)
        same, again = catalog.add_product(self.db, "мляко", "Млечни", "бр", ["мляко"])
        self.assertFalse(again)
        self.assertEqual(product["id"], same["id"])
        self.assertEqual(same["unit"], "бр")

    def test_offers_sorted_and_updated(self):
        self.fill()
        product = catalog.find_product(self.db, "мляко")
        offers = catalog.offers_for(self.db, product["id"])
        self.assertEqual(offers[0][1]["price"], 2.29)
        catalog.set_offer(self.db, "мляко", "Лидл", "1.99")
        offers = catalog.offers_for(self.db, product["id"])
        self.assertEqual(offers[0][1]["price"], 1.99)
        self.assertEqual(len(offers), 2)

    def test_set_offer_rejects_bad_price(self):
        self.fill()
        with self.assertRaises(PazarError):
            catalog.set_offer(self.db, "мляко", "Лидл", "скъпо")
        with self.assertRaises(PazarError):
            catalog.set_offer(self.db, "мляко", "Лидл", "-1")

    def test_find_product_unique_prefix(self):
        self.fill()
        product = catalog.find_product(self.db, "мля")
        self.assertIsNotNone(product)
        self.assertEqual(product["name"], "Мляко 3% 1 л")

    def test_search_finds_by_keyword(self):
        self.fill()
        results = catalog.search(self.db, "мляко")
        self.assertTrue(results)
        self.assertEqual(results[0][0]["name"], "Мляко 3% 1 л")
        self.assertEqual(results[0][1][0][1]["price"], 2.29)

    def test_compare_splits_and_single_store(self):
        self.fill()
        result = catalog.compare(self.db, [
            {"name": "мляко", "qty": 1},
            {"name": "хляб", "qty": 2},
            {"name": "яйца", "qty": 1},
        ])
        self.assertEqual(result["count"], 3)
        # най-евтиното: мляко Лидл 2.29, хляб Лидл 2.58, яйца Кауфланд 4.59
        self.assertEqual(result["split_total"], 9.46)
        self.assertEqual(len(result["by_store"]), 2)
        self.assertEqual(result["single"]["store"]["name"], "Кауфланд")
        self.assertTrue(result["single"].get("complete", True))

    def test_compare_reports_missing(self):
        self.fill()
        result = catalog.compare(self.db, [{"name": "само това го няма", "qty": 1}])
        self.assertEqual(result["missing"], ["само това го няма"])
        self.assertEqual(result["split_total"], 0.0)


class ShoppingTests(Base):
    def test_add_and_estimate(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко*2", "хляб"])
        self.assertEqual(len(lst["items"]), 2)
        milk = next(i for i in lst["items"] if i["name"].startswith("Мляко"))
        self.assertEqual(milk["qty"], 2)
        self.assertEqual(milk["store_id"], catalog.require_store(self.db, "Лидл")["id"])
        price, store_id = shopping.estimate(self.db, milk)
        self.assertEqual(price, 2.29)
        self.assertIsNotNone(store_id)

    def test_add_merges_same_item(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко*2"])
        shopping.add_items(self.db, lst["id"], ["мляко*3"])
        self.assertEqual(len(lst["items"]), 1)
        self.assertEqual(lst["items"][0]["qty"], 5)

    def test_plan_stores_moves_to_cheapest(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко"], store_ref="Кауфланд")
        changed = shopping.plan_stores(self.db, lst["id"])
        self.assertEqual(changed, 1)
        self.assertEqual(lst["items"][0]["store_id"],
                         catalog.require_store(self.db, "Лидл")["id"])

    def test_list_totals(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко*2", "яйца"])
        totals = shopping.list_totals(self.db, lst)
        self.assertEqual(totals["total"], 4.58 + 4.59)
        self.assertEqual(totals["pending"], 2)
        self.assertEqual(totals["bought_total"], 0.0)

    def test_record_purchase_and_delete(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко*2", "яйца"])
        created = shopping.record_purchase(
            self.db, lst["id"], price_args=["мляко=2.10", "яйца=4.50"])
        self.assertEqual(len(created), 2)  # по един запис на магазин
        purchase = created[0]
        self.assertEqual(sum(p["total"] for p in created), 4.20 + 4.50)
        self.assertTrue(all(i.get("bought") for i in lst["items"]))
        self.assertEqual(lst["status"], "done")
        self.assertEqual(len(self.db.purchases), 2)

        removed = shopping.delete_purchase(self.db, purchase["id"])
        self.assertEqual(removed["id"], purchase["id"])
        self.assertEqual(len(self.db.purchases), 1)
        bought = [i for i in lst["items"] if i.get("bought")]
        self.assertEqual(len(bought), 1)  # само яйцата остават купени
        self.assertEqual(lst["status"], "active")
        shopping.delete_purchase(self.db, created[1]["id"])
        self.assertEqual(self.db.purchases, [])
        self.assertFalse(any(i.get("bought") for i in lst["items"]))

    def test_record_purchase_requires_price(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко"])
        with self.assertRaises(PazarError):
            shopping.record_purchase(self.db, lst["id"])

    def test_record_purchase_from_file(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко", "хляб"])
        path = self.root / "prices.csv"
        path.write_text(
            "name,unit_price\n"
            "мляко,2.00\n"
            "хляб,1.10\n",
            encoding="utf-8",
        )
        created = shopping.record_purchase(self.db, lst["id"], file_path=str(path))
        self.assertEqual(sum(p["total"] for p in created), 3.10)

    def test_item_matching_by_number_and_name(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко", "хляб"])
        shopping.remove_items(self.db, lst["id"], ["1"])
        self.assertEqual([i["name"] for i in lst["items"]], ["Хляб бял 500 г"])


class ReportTests(Base):
    def _purchases(self):
        self.fill()
        lst = shopping.new_list(self.db, "Тест")
        shopping.add_items(self.db, lst["id"], ["мляко", "яйца"])
        shopping.record_purchase(self.db, lst["id"], price_args=["мляко=2.00", "яйца=4.00"],
                                 when="2026-03-05")
        return lst

    def test_collect_by_month_and_store(self):
        self._purchases()
        rep = report.collect(self.db, month="2026-03")
        self.assertEqual(rep["label"], "март 2026")
        self.assertEqual(rep["total"], 6.0)
        self.assertEqual(rep["count"], 2)  # мляко в Лидл и яйца в Кауфланд
        self.assertEqual(rep["average"], 3.0)
        self.assertEqual(dict(rep["by_store"])["Кауфланд"], 4.0)
        self.assertEqual(dict(rep["by_category"])["Млечни"], 6.0)

    def test_budget(self):
        self._purchases()
        self.db.settings["budget_month"] = 10
        rep = report.collect(self.db, month="2026-03")
        self.assertEqual(rep["budget"], 10.0)
        self.assertEqual(rep["spent_share"], 60.0)
        self.assertEqual(rep["remaining"], 4.0)

    def test_format_text_and_html(self):
        self._purchases()
        rep = report.collect(self.db, month="2026-03")
        text = report.format_text(rep)
        self.assertIn("ОТЧЕТ", text)
        self.assertIn("6.00 лв", text)
        page = report.format_html(rep)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("март 2026", page)

    def test_empty_period(self):
        rep = report.collect(self.db, month="2020-01")
        self.assertEqual(rep["total"], 0.0)
        self.assertIn("Няма записани покупки", report.format_text(rep))


class CliTests(Base):
    def test_full_flow(self):
        code, out = self.run_cli(["demo"])
        self.assertEqual(code, 0)
        self.assertIn("Заредени", out)
        self.db = DB(self.root)  # CLI работи със собствено зареждане
        self.assertTrue(self.db.stores)
        self.assertTrue(self.db.products)

        code, out = self.run_cli(["store", "ls"])
        self.assertEqual(code, 0)
        self.assertIn("Лидл", out)

        code, out = self.run_cli(["search", "мляко"])
        self.assertEqual(code, 0)
        self.assertIn("Мляко", out)

        code, out = self.run_cli(["compare", "мляко", "хляб*2"])
        self.assertEqual(code, 0)
        self.assertIn("Най-евтино общо", out)

        code, out = self.run_cli(["list", "new", "Седмичен"])
        self.assertEqual(code, 0)
        self.assertIn("Създаден списък", out)

        code, out = self.run_cli(["list", "add", "мляко*2", "хляб бял", "яйца"])
        self.assertEqual(code, 0)
        self.assertIn("мляко", out.lower())

        # нееднозначно име: добавя се, но с подсказка; после го махаме
        code, out = self.run_cli(["list", "add", "хляб", "--list", "Седмичен"])
        self.assertEqual(code, 0)
        self.assertIn("възможни съвпадения", out)
        code, out = self.run_cli(["list", "rm", "хляб", "--list", "Седмичен"])
        self.assertEqual(code, 0)

        code, out = self.run_cli(["list", "show"])
        self.assertEqual(code, 0)
        self.assertIn("Седмичен", out)
        self.assertIn("Оценена сума", out)

        code, out = self.run_cli(["budget", "set", "400"])
        self.assertEqual(code, 0)
        self.assertIn("Месечен бюджет", out)

        code, out = self.run_cli(["buy", "--use-estimates"])
        self.assertEqual(code, 0)
        self.assertIn("Записана покупка", out)

        code, out = self.run_cli(["purchase", "ls"])
        self.assertEqual(code, 0)
        self.assertIn("Общо", out)

        code, out = self.run_cli(["report", "--all"])
        self.assertEqual(code, 0)
        self.assertIn("ОТЧЕТ", out)

        html_path = self.root / "report.html"
        code, out = self.run_cli(["report", "--all", "--html", str(html_path)])
        self.assertEqual(code, 0)
        self.assertTrue(html_path.exists())
        self.assertIn("<!DOCTYPE html>", html_path.read_text(encoding="utf-8"))

        list_id = DB(self.root).lists[0]["id"]  # списъкът вече е „завършен“
        code, out = self.run_cli(["list", "export", list_id,
                                  "--file", str(self.root / "export.csv")])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "export.csv").exists())

    def test_demo_data_file_is_valid(self):
        path = Path(__file__).resolve().parent.parent / "examples" / "demo.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["stores"])
        self.assertTrue(data["products"])
        for product in data["products"]:
            self.assertTrue(product["name"])
            for store, price in product["offers"]:
                self.assertGreater(tx.to_number(price), 0)

    def test_errors_are_reported(self):
        code, _ = self.run_cli(["store", "add", "Ето такъв"])
        self.assertEqual(code, 0)
        code, _ = self.run_cli(["price", "set", "няма такъв", "Лидл", "1.00"])
        self.assertEqual(code, 2)
        code, _ = self.run_cli(["report", "--month", "2026-13"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)