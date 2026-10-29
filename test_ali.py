"""AliExpress read paths: the site's API JSON and the product page's text -> the text the tools return.
No requests to shops.  Run: .venv/bin/python -B -m unittest -v test_ali"""
import datetime
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import ali


def answer(body, status=200):
    return {"s": status, "b": body if isinstance(body, str) else json.dumps(body)}


class FetchTests(unittest.TestCase):
    def fetch(self, *answers, last_call=0.0, call=lambda tab: ali._fetch(tab, "/aer-webapi/v1/search", {"page": 1})):
        tab = MagicMock()
        tab.js.side_effect = list(answers)
        ali._last_call = last_call
        with patch.object(ali.time, "sleep") as sleep, patch.object(ali, "dump", return_value="logs/bodies/x.html"), \
                patch.object(ali, "log") as log:
            try:
                return call(tab), tab, sleep, log
            except RuntimeError as e:
                return e, tab, sleep, log

    def test_post_with_json_body(self):
        got, tab, sleep, _ = self.fetch(answer({"data": {}}))
        self.assertEqual(got, {"data": {}})
        self.assertEqual(tab.js.call_args.args[0],
                         'Promise.race([fetch("/aer-webapi/v1/search", {"method": "POST", "credentials": "include", '
                         '"headers": {"Content-Type": "application/json"}, "body": "{\\"page\\": 1}"})'
                         '.then(async r => ({s: r.status, b: await r.text()})), new Promise(res => setTimeout(() => res(null), 25000))])')
        self.assertEqual(tab.js.call_args.kwargs, {"timeout": 40})
        sleep.assert_not_called()

    def test_product_data_is_a_get_without_body(self):
        got, tab, _, _ = self.fetch(answer({"data": {"reviews": 5}}), call=lambda tab: ali._product_data(tab, "1005006043702745"))
        self.assertEqual(got, {"data": {"reviews": 5}})
        self.assertIn('fetch("/aer-jsonapi/v1/bx/pdp/web/productData?productId=1005006043702745&sourceId=0&sku_id=0", '
                      '{"method": "GET", "credentials": "include", "headers": {"Content-Type": "application/json"}})',
                      tab.js.call_args.args[0])

    def test_waits_out_the_gap_since_the_last_call(self):
        _, _, sleep, _ = self.fetch(answer({}), last_call=time.time())
        self.assertGreater(sleep.call_args.args[0], 1.0)
        self.assertLessEqual(sleep.call_args.args[0], 1.5)

    def test_slider_check_holding_the_request(self):
        got, tab, _, _ = self.fetch(None, True)
        self.assertEqual(str(got), "⚠️ AliExpress показал проверку на бота (слайдер) и держит запросы: shop-chrome show, "
                                   "пройти её во вкладке aliexpress.ru, shop-chrome hide")
        self.assertEqual(tab.js.call_args.args[0], "!!document.querySelector('.baxia-dialog-content')")

    def test_no_answer_in_25_seconds(self):
        got, _, _, _ = self.fetch(None, False)
        self.assertEqual(str(got), "AliExpress не ответил за 25 с на /aer-webapi/v1/search")

    def test_non_json_reloads_the_tab_and_retries(self):
        got, tab, sleep, log = self.fetch(answer("<html>antibot</html>", 403), answer({"data": {"ok": 1}}))
        self.assertEqual(got, {"data": {"ok": 1}})
        tab.goto.assert_called_once_with("https://aliexpress.ru/", "ali", wait_js="document.readyState === 'complete'")
        self.assertEqual(sleep.call_args_list[0].args, (3,))        # then the retry waits out its own gap
        self.assertEqual(log.warning.call_args.args[1:], ("POST", "/aer-webapi/v1/search", 403, "logs/bodies/x.html"))

    def test_non_json_twice_raises_with_the_saved_body(self):
        got, tab, _, log = self.fetch(answer("<html>1</html>", 403), answer("<html>2</html>", 403))
        self.assertEqual(str(got), "AliExpress ответил 403 не-JSON и после перезагрузки вкладки "
                                   "(вероятно, проверка на бота: shop-chrome show). Ответ целиком: logs/bodies/x.html")
        self.assertEqual(tab.goto.call_count, 1)
        log.error.assert_called_once()


def by(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).strftime("%d.%m")


def product(pid, title, price, delivery=(), exp=None, sold="950 купили", store="Test Store"):
    """One productsV2 entry: the item sits deep in the tile, the delivery snippet in its layout areas."""
    item = {"properties": {"id": pid, "preselectSkuId": f"12000{pid}"},
            "pdpInfo": {"preloadedData": {"price": {"value": price}, "title": title, "rating": "4.7", "salesCount": sold,
                                          "store": {"name": store}}},
            "trackingInfo": {"utLogMap": [{"exp_attribute": exp}] if exp else []}}
    areas = [{"id": {"name": "priceArea"}, "blocks": [{"text": f"{price} ₽"}]}]
    if delivery:
        areas.append({"id": {"name": "deliverySnippet"}, "blocks": [{"text": t} for t in delivery]})
    return {"type": "product", "widgets": [{"data": {"itemData": item}}], "layoutAreas": areas}


BANNER = {"type": "banner", "widgets": [{"data": {"image": "x.jpg"}}], "layoutAreas": []}
P1 = product("1005008606048009", "Toocki USB Type C Кабель 100 Вт", 209, ["до 14 дней", "бесплатно"])
P2 = product("1005008364835496", "PD 60 Вт USB C кабель " + "длинное название " * 8, 289,
             exp={"snippet_delivery_eta": "11-14", "delivery_price": "20"}, sold="18 906 купили")
P3 = product("1005006043702745", "Кабель Essager", 131, ["Доставка 5 ноября"], exp={"snippet_delivery_eta": "7-9"})
P4 = product("1005009405736390", "Кабель без доставки", 88, exp={"snippet_delivery_eta": "10-12"})
P5 = product("1005001111111111", "Кабель без срока", 99, store="")
SEARCH_HEAD = ("AliExpress · товар: https://aliexpress.ru/item/<id>.html\n"
               "«привезут до» = сегодня + максимальный срок из карточки; точная дата — в ali_item\n"
               "#\tid\tsku\tцена ₽\tназвание\tрейтинг\tкупили\tпривезут до\tдоставка (срок, цена)\tмагазин")


def results(products, pages=2):
    return {"data": {"pagination": {"totalPages": pages}, "productsFeed": {"productsV2": products}}}


class SearchTests(unittest.TestCase):
    def search(self, answers, query="кабель usb-c", **kw):
        tab, sent = MagicMock(), []

        def fetch(_tab, path, body):
            self.assertEqual(path, "/aer-webapi/v1/search")
            sent.append(dict(body))             # search() changes the same dict for the next page
            return answers[len(sent) - 1]
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", side_effect=fetch):
            out = ali.search(query, **kw)
        tab.close.assert_called_once()
        return out, sent

    def test_rows_across_pages(self):
        out, sent = self.search([results([P1, BANNER, P2]), results([P1, P3, P4, P5])])
        self.assertEqual([b["page"] for b in sent], [1, 2])
        self.assertEqual(sent[0], {"catId": "", "searchInfo": "", "searchText": "кабель usb-c", "page": 1, "storeIds": [],
                                   "pgChildren": [], "aeBrainIds": [], "searchTrigger": "search_bar", "mainFilters": "",
                                   "source": "direct"})
        self.assertEqual(out, SEARCH_HEAD + "\n" + "\n".join([
            f"1\t1005008606048009\t120001005008606048009\t209\tToocki USB Type C Кабель 100 Вт\t4.7\t950\t{by(14)}\t"
            "до 14 дней, бесплатно\tTest Store",
            "2\t1005008364835496\t120001005008364835496\t289\t" + ("PD 60 Вт USB C кабель " + "длинное название " * 8)[:110]
            + f"\t4.7\t18 906\t{by(14)}\t11-14 дн., 20 ₽\tTest Store",
            f"3\t1005006043702745\t120001005006043702745\t131\tКабель Essager\t4.7\t950\t{by(9)}\tДоставка 5 ноября\tTest Store",
            f"4\t1005009405736390\t120001005009405736390\t88\tКабель без доставки\t4.7\t950\t{by(12)}\t10-12 дн., бесплатно\tTest Store",
            "5\t1005001111111111\t120001005001111111111\t99\tКабель без срока\t4.7\t950\t\t\t"]))

    def test_sort_and_price_range_go_into_the_request(self):
        out, sent = self.search([{"data": None}], sort="orders", price_min=100.5, price_max=500)
        self.assertEqual({k: sent[0][k] for k in ("sortType", "minPrice", "maxPrice")},
                         {"sortType": "total_tranpro_desc", "minPrice": 100, "maxPrice": 500})
        self.assertEqual(out, SEARCH_HEAD + "\n(пусто)")
        self.assertNotIn("sortType", self.search([{"data": None}])[1][0])

    def test_limit_stops_reading_pages(self):
        out, sent = self.search([results([P1, P2])], limit=1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(out.splitlines()[3:], [f"1\t1005008606048009\t120001005008606048009\t209\tToocki USB Type C Кабель 100 Вт\t"
                                                f"4.7\t950\t{by(14)}\tдо 14 дней, бесплатно\tTest Store"])

    def test_reads_at_most_five_pages(self):
        out, sent = self.search([results([product(f"10050000000000{n:02}", f"товар {n}", n)], pages=9) for n in range(1, 10)],
                                limit=100)
        self.assertEqual(len(sent), 5)
        self.assertTrue(out.splitlines()[-1].startswith("5\t1005000000000005\t"))

    def test_unknown_sort(self):
        with self.assertRaisesRegex(ValueError, "sort: одно из"):
            ali.search("usb", sort="rating")


if __name__ == "__main__":
    unittest.main()
