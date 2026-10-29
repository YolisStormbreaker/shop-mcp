"""Order history: the Ozon and AliExpress order lists and order pages -> the search answer, and what is cached.
No requests to shops; the cache is a temp file, never cache/orders.json.  Run: .venv/bin/python -B -m unittest -v test_orders"""
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import ali
import orders
import ozon

NOW = time.mktime((2026, 10, 29, 12, 0, 0, 0, 0, -1))
FEB_2026 = time.mktime((2026, 2, 1, 0, 0, 0, 0, 0, -1))
HEAD = "заказ\tдата / статус\tсумма\tтовар\tвариант\tцена\tссылка"
CAPPED = (" (достиг предела новых загрузок за вызов; просмотренные закэшированы — "
          "повтори тот же вызов, чтобы искать дальше)")


class CacheInTempDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "cache" / "orders.json"
        self.log, self.sleep = MagicMock(), MagicMock()
        for p in (patch.object(orders, "CACHE", self.file), patch.object(orders, "log", self.log),
                  patch.object(orders.time, "time", return_value=NOW), patch.object(orders.time, "sleep", self.sleep),
                  patch.object(ali, "_last_call", NOW - 1.0)):          # the last request to Ali a second ago
            p.start()
            self.addCleanup(p.stop)

    def seed(self, entries):
        self.file.parent.mkdir()
        self.file.write_text(json.dumps(entries), encoding="utf-8")

    def cached(self):
        return json.loads(self.file.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ Ozon
def page(widgets=None, **top):
    """An Ozon composer page: its widget states are JSON strings."""
    return {"widgetStates": {k: json.dumps(v) for k, v in (widgets or {}).items()}, **top}


def tile(oid, status):
    return {"leftBlock": {"textIcon": {"text": {"text": status},
                                       "common": {"action": {"link": f"/my/orderdetails/?order={oid}&selectedTab=archive"}}}}}


def order_list(*tiles, nxt=None):
    w = {"orderList-1-default-1": {"ordersV2": list(tiles)}}
    if nxt:  # next to the order list's own paginator, one for recommendations
        w["paginator-2-default-1"] = {"layoutContainer": "recommendations", "nextPage": "/my/orderlist/reco?page=2"}
        w["paginator-3-default-1"] = {"layoutContainer": "order-list-paginator", "nextPage": nxt}
    return page(w)


def product(name, slug=None, prices=(), attributes=()):
    p = {"title": {"name": {"text": name}}}
    if slug:
        p["title"]["common"] = {"action": {"link": f"/product/{slug}/?from=orders"}}
    if prices:
        p["price"] = {"price": list(prices)}
    if attributes:
        p["attributes"] = [{"text": a} for a in attributes]
    return p


def details(*sellers, done=None, total=None):
    """Order page: each seller is (name, [products]) in a shipment of its own."""
    w = {"shipmentWidget-1": {"items": [{"sellers": [{"name": {"text": s}, "products": ps}]} for s, ps in sellers]}}
    if done is not None:
        w["orderDoneTotal-2"] = {"total": {"right": {"price": {"text": done}}}}
    if total is not None:
        w["orderTotal-3"] = {"total": {"right": {"price": {"text": total}}}}
    return page(w)


A1, A2, F26, F25 = "10000001-0001", "10000002-0001", "20260001-0001", "20250001-0001"
LONG = "Набор прецизионных отвёрток " + "с битами и держателем " * 6
OPTION = "Комплектация: " + "кейс, " * 12
YEARS = page({"orderFilters-1": {"tagButtons": [{"text": "Все"}, {"text": "2025"}, {"text": "2026"}, {"text": "2025"},
                                                {"text": "2026 г."}]}})
OZON = {
    "/my/orderlist?selectedTab=archive": YEARS,
    "/my/orderlist": order_list(tile(A1, "В пути"), {"leftBlock": {"textIcon": {"text": {"text": "Реклама"}}}},
                                nxt="/my/orderlist?page=2"),
    "/my/orderlist?page=2": page({"orderList-1": {"ordersV2": [tile(A2, "Можно забирать")]}},
                                 nextPage="/highlight/recommendations?page=3"),
    "/my/orderlist?selectedTab=archive&selectedYear=2026": order_list(tile(F26, "Получен"), tile(A2, "Получен")),
    # a tile without the usual link: its id is found anywhere in the tile
    "/my/orderlist?selectedTab=archive&selectedYear=2025": page({"orderList-1": {"ordersV2": [
        {"leftBlock": {"textIcon": {"text": {"text": "Отменён"}}}, "rightBlock": {"link": f"/my/orderdetails/?order={F25}"}}]}}),
    "/my/orderdetails/?order=" + A1: details(("ООО Ромашка", [product(
        "Кабель USB-C 1 м", "kabel-usb-c-100001", attributes=("Цвет: чёрный", "Длина: 1 м"),
        prices=({"text": "1 299 ₽", "textStyle": "PRICE"}, {"text": "1 599 ₽", "textStyle": "ORIGINAL_PRICE"}))]),
        total="1 299 ₽"),
    "/my/orderdetails/?order=" + A2: details(("ИП Лютиков", [product("Зарядка 65 Вт", "zaryadka-100002",
                                                                       prices=({"text": "2 490 ₽"},))]),
                                             ("Ozon", [product("Подарок")]), done="2 490 ₽", total=""),
    "/my/orderdetails/?order=" + F26: details(("ООО Ромашка", [product(LONG, "nabor-100003", attributes=(OPTION,),
                                                                        prices=({"text": "990 ₽"},))]), done="990 ₽"),
    "/my/orderdetails/?order=" + F25: details(("ООО Ромашка", [product("Термопаста", "termopasta-100004",
                                                                        prices=({"text": "350 ₽"},))]), done="350 ₽"),
}
ROWS = {
    A1: [f"{A1}\tВ пути\t1 299 ₽\tКабель USB-C 1 м\tЦвет: чёрный; Длина: 1 м\t1 299 ₽\thttps://www.ozon.ru/product/kabel-usb-c-100001/"],
    A2: [f"{A2}\tМожно забирать\t2 490 ₽\tЗарядка 65 Вт\t\t2 490 ₽\thttps://www.ozon.ru/product/zaryadka-100002/",
         f"{A2}\tМожно забирать\t2 490 ₽\tПодарок\t\t\t"],
    F26: [f"{F26}\tПолучен (2026)\t990 ₽\t{LONG[:110]}\t{OPTION[:50]}\t990 ₽\thttps://www.ozon.ru/product/nabor-100003/"],
    F25: [f"{F25}\tОтменён (2025)\t350 ₽\tТермопаста\t\t350 ₽\thttps://www.ozon.ru/product/termopasta-100004/"],
}
LISTS = ["/my/orderlist?selectedTab=archive", "/my/orderlist", "/my/orderlist?page=2",
         "/my/orderlist?selectedTab=archive&selectedYear=2026", "/my/orderlist?selectedTab=archive&selectedYear=2025"]


def answer(header, *oids):
    return "\n".join([header, HEAD] + [r for o in oids for r in ROWS[o]])


class OzonOrdersTests(CacheInTempDir):
    def ozon_orders(self, pages=OZON, **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), \
                patch.object(ozon, "_page", side_effect=lambda t, url: pages[url]) as get:
            out = orders.ozon_orders(**kw)
        self.assertTrue(all(c.args[0] is tab for c in get.call_args_list))
        tab.close.assert_called_once_with()
        return out, [c.args[1] for c in get.call_args_list]

    def test_first_call_reads_every_list_and_order(self):
        out, urls = self.ozon_orders()
        self.assertEqual(out, answer("Ozon: заказы — найдено 4, просмотрено заказов 4", A1, A2, F26, F25))
        self.assertEqual(urls, LISTS + ["/my/orderdetails/?order=" + o for o in (A1, A2, F26, F25)])
        self.log.info.assert_called_once_with("ozon_orders %r: %d found, %d scanned, %d fetched", None, 4, 4, 4)
        c = self.cached()
        self.assertEqual(c["ozon:live"], {"at": NOW, "years": [2026, 2025],
                                          "active": [[A1, "В пути"], [A2, "Можно забирать"]]})
        self.assertEqual(c["ozon:list:2026"], {"at": NOW, "ids": [[F26, "Получен"], [A2, "Получен"]]})
        self.assertEqual(c["ozon:list:2025"], {"at": NOW, "ids": [[F25, "Отменён"]]})
        self.assertEqual(c["ozon:" + A2], {"id": A2, "total": "2 490 ₽", "at": NOW, "products": [
            {"title": "Зарядка 65 Вт", "variant": "", "price": "2 490 ₽", "url": "https://www.ozon.ru/product/zaryadka-100002/",
             "seller": "ИП Лютиков"},
            {"title": "Подарок", "variant": "", "price": "", "url": "", "seller": "Ozon"}]})
        self.assertNotIn("at", c["ozon:" + F26])          # a finished order is never read again
        self.assertEqual(len(c), 7)

    def test_second_call_makes_no_requests(self):
        first, _ = self.ozon_orders()
        out, urls = self.ozon_orders()
        self.assertEqual(out, first)
        self.assertEqual(urls, [])

    def test_query_with_alternatives(self):
        out, _ = self.ozon_orders(query="кабель | термопаста")
        self.assertEqual(out, answer("Ozon: заказы с «кабель | термопаста» в названии — найдено 2, просмотрено заказов 4",
                                     A1, F25))

    def test_limit_stops_reading(self):
        out, urls = self.ozon_orders(query="кабель | зарядка", limit=1)
        self.assertEqual(out, answer("Ozon: заказы с «кабель | зарядка» в названии — найдено 1, просмотрено заказов 1", A1))
        self.assertEqual(urls[-1], "/my/orderdetails/?order=" + A1)

    def test_nothing_found(self):
        out, _ = self.ozon_orders(query="паяльник")
        self.assertEqual(out, "Ozon: заказы с «паяльник» в названии — найдено 0, просмотрено заказов 4\n(ничего)")

    def test_cap_on_new_orders_then_the_same_call_goes_on(self):
        out, _ = self.ozon_orders(max_new=1)
        self.assertEqual(out, answer("Ozon: заказы — найдено 1, просмотрено заказов 1" + CAPPED, A1))
        out, urls = self.ozon_orders(max_new=1)
        self.assertEqual(out, answer("Ozon: заказы — найдено 2, просмотрено заказов 2" + CAPPED, A1, A2))
        self.assertEqual(urls, ["/my/orderdetails/?order=" + A2])
        self.log.info.assert_called_with("ozon_orders %r: %d found, %d scanned, %d fetched", None, 2, 2, 1)

    def test_one_year(self):
        self.ozon_orders(max_new=0)                 # lists only
        out, urls = self.ozon_orders(year=2024, pages={
            **OZON, "/my/orderlist?selectedTab=archive&selectedYear=2024": order_list(tile(F25, "Получен"))})
        self.assertEqual(urls, ["/my/orderlist?selectedTab=archive&selectedYear=2024", "/my/orderdetails/?order=" + A1,
                                "/my/orderdetails/?order=" + A2, "/my/orderdetails/?order=" + F25])
        self.assertEqual(out.splitlines()[-1], ROWS[F25][0].replace("Отменён (2025)", "Получен (2024)"))
        self.assertEqual(self.cached()["ozon:list:2024"], {"at": NOW, "ids": [[F25, "Получен"]]})

    def test_details_are_read_again_only_when_stale(self):
        def saved(oid, at=None):
            o = {"id": oid, "total": "1 ₽", "products": [{"title": "из кэша"}]}
            return dict(o, at=at) if at else o
        self.seed({"ozon:live": {"at": NOW - 60, "years": [2026], "active": [[A1, "В пути"], [A2, "Можно забирать"]]},
                   "ozon:list:2026": {"at": NOW - 60, "ids": [[F26, "Получен"], [F25, "Получен"]]},
                   "ozon:" + A1: saved(A1, NOW - orders.ACTIVE_TTL),             # on its way, read exactly a day ago
                   "ozon:" + A2: saved(A2, NOW - orders.ACTIVE_TTL - 1),         # on its way, read over a day ago
                   "ozon:" + F26: saved(F26, NOW - 60),                          # read on its way, finished since
                   "ozon:" + F25: saved(F25)})                                   # read when finished
        out, urls = self.ozon_orders()
        self.assertEqual(urls, ["/my/orderdetails/?order=" + A2, "/my/orderdetails/?order=" + F26])
        self.assertEqual(out.splitlines()[2:], [f"{A1}\tВ пути\t1 ₽\tиз кэша\t\t\t", *ROWS[A2],
                                                *ROWS[F26],
                                                f"{F25}\tПолучен (2026)\t1 ₽\tиз кэша\t\t\t"])
        c = self.cached()
        self.assertEqual(c["ozon:" + A2]["at"], NOW)
        self.assertNotIn("at", c["ozon:" + F26])

    def test_saved_lists_are_refreshed_from_the_top(self):
        K1, K2, K3, N1 = "20260011-0001", "20260012-0001", "20260013-0001", "20260014-0001"
        self.seed({"ozon:live": {"at": NOW - orders.LIVE_TTL, "years": [2026], "active": []},
                   # saved after January of the next year: final, not read again
                   "ozon:list:2025": {"at": FEB_2026 + 1, "ids": [[F25, "Получен"]]},
                   # saved by the end of January: late December orders may still arrive
                   "ozon:list:2024": {"at": time.mktime((2025, 2, 1, 0, 0, 0, 0, 0, -1)), "ids": [[K3, "Получен"]]},
                   "ozon:list:2026": {"at": NOW - 3600, "ids": [[K1, "Получен"], [K2, "Получен"], [K3, "Получен"]]},
                   **{"ozon:" + k: {"id": k, "total": "", "products": []} for k in (K1, K2, K3, F25, A1)}})
        archive = "/my/orderlist?selectedTab=archive"
        pages = {archive: page({"orderFilters-1": {"tagButtons": [{"text": "2026"}, {"text": "2025"}, {"text": "2024"}]}}),
                 "/my/orderlist": order_list(tile(A1, "В пути")),
                 archive + "&selectedYear=2026": order_list(tile(N1, "Получен"), tile(K1, "Получен"), nxt="/my/orderlist?p=2"),
                 "/my/orderlist?p=2": page({"orderList-1": {"ordersV2": [tile(K2, "Получен")]}}, nextPage="/my/orderlist?p=3"),
                 archive + "&selectedYear=2024": order_list(tile(K3, "Получен")),
                 "/my/orderdetails/?order=" + N1: details(("ООО Ромашка", [product("Новое")]))}
        out, urls = self.ozon_orders(pages=pages)
        self.assertEqual(urls, [archive, "/my/orderlist", archive + "&selectedYear=2026", "/my/orderlist?p=2",
                                archive + "&selectedYear=2024", "/my/orderdetails/?order=" + N1])
        c = self.cached()
        self.assertEqual(c["ozon:list:2026"]["ids"], [[N1, "Получен"], [K1, "Получен"], [K2, "Получен"], [K3, "Получен"]])
        self.assertEqual(c["ozon:list:2025"]["at"], FEB_2026 + 1)
        self.assertEqual(c["ozon:list:2024"], {"at": NOW, "ids": [[K3, "Получен"]]})
        self.assertEqual(c["ozon:live"], {"at": NOW, "years": [2026, 2025, 2024], "active": [[A1, "В пути"]]})
        self.assertIn("просмотрено заказов 6", out)

    def test_narrow_no_break_spaces_in_prices_become_plain(self):
        pages = {**OZON, "/my/orderdetails/?order=" + A1: details(("ООО Ромашка", [product(
            "Кабель USB-C 1 м", "kabel-usb-c-100001", attributes=("Цвет: чёрный", "Длина: 1 м"),
            prices=({"text": "1\u202f299\u202f₽"},))]), total="1\u202f299\u202f₽")}
        out, _ = self.ozon_orders(pages=pages, query="кабель")
        self.assertEqual(out, answer("Ozon: заказы с «кабель» в названии — найдено 1, просмотрено заказов 4", A1))

    def test_tab_is_closed_when_a_request_fails(self):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_page", side_effect=RuntimeError("бот")):
            with self.assertRaisesRegex(RuntimeError, "бот"):
                orders.ozon_orders()
        tab.close.assert_called_once_with()
        self.assertFalse(self.file.exists())


# ------------------------------------------------------------------------------ AliExpress
def ali_order(oid, total, *items, status=None, tag=None):
    od = {"orderId": oid, "totalPrice": total, "products": [{"itemId": i} for i in items]}
    if status is not None:
        od["statusInfo"] = {"title": status}
    if tag:
        od["tag"] = {"title": tag}
    return od


def ali_page(*ods, more=False):
    return {"data": {"items": [{"orders": list(ods)}], "hasMore": more}}


def ali_detail(date, title, item):
    return {"date": date, "n": 1000, "products": [
        {"title": title, "variant": "EU", "price": "1 000 ₽", "url": f"https://aliexpress.ru/item/{item}.html"}]}


B1, B2, B3, B4 = "8000000000000001", "8000000000000002", "8000000000000003", "8000000000000004"
ALI_LISTS = {
    ("active", 1): ali_page(ali_order(B1, "1 234,56 ₽", "1005001", status="Ожидает получения"), {"orderId": ""}, more=True),
    ("active", 2): ali_page(ali_order(B2, "500 ₽", "1005002", status="", tag="Отправлен")),
    ("archive", 1): ali_page(ali_order(B3, "990 ₽", "1005003", status="Завершён"), ali_order(B4, "", "1005004", "1005005"),
                             ali_order(B2, "500 ₽", "1005002", status="Получен")),       # already in the active list
}
ALI_DETAILS = {B1: ali_detail("1 октября 2026", "Паяльник T12", "1005001"), B2: ali_detail("", "Жало K", "1005002"),
               B3: ali_detail("5 мая 2026", "Флюс", "1005003"), B4: None}
ALI_ROWS = [f"{B1}\t1 октября 2026 · Ожидает получения\t1 234,56 ₽\tПаяльник T12\tEU\t1 000 ₽\thttps://aliexpress.ru/item/1005001.html",
            f"{B2}\tОтправлен\t500 ₽\tЖало K\tEU\t1 000 ₽\thttps://aliexpress.ru/item/1005002.html",
            f"{B3}\t5 мая 2026 · Завершён\t990 ₽\tФлюс\tEU\t1 000 ₽\thttps://aliexpress.ru/item/1005003.html",
            f"{B4}\t\t\t(не прочитал название) товар 1005004\t\t\thttps://aliexpress.ru/item/1005004.html",
            f"{B4}\t\t\t(не прочитал название) товар 1005005\t\t\thttps://aliexpress.ru/item/1005005.html"]


class AliOrdersTests(CacheInTempDir):
    def ali_orders(self, lists=ALI_LISTS, dets=ALI_DETAILS, **kw):
        tab = MagicMock()
        tab.js.side_effect = lambda js, timeout: dets[re.search(r'fetch\("/order-list/(\d+)"', js).group(1)]

        def fetch(t, path, body):
            self.assertIs(t, tab)
            self.assertEqual((path, body["pageSize"]), (orders.ALI_LIST, 20))
            return lists[body["tabType"], body["page"]]
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", side_effect=fetch) as f:
            out = orders.ali_orders(**kw)
        tab.close.assert_called_once_with()
        self.assertTrue(all(c.kwargs == {"timeout": 60} for c in tab.js.call_args_list))
        return (out, [(c.args[2]["tabType"], c.args[2]["page"]) for c in f.call_args_list],
                [re.search(r"/order-list/(\d+)", c.args[0]).group(1) for c in tab.js.call_args_list])

    def test_first_call_reads_both_lists_and_every_order(self):
        out, pages, read = self.ali_orders()
        self.assertEqual(out, "\n".join(["AliExpress: заказы — найдено 4, просмотрено заказов 4", HEAD] + ALI_ROWS))
        self.assertEqual(pages, [("active", 1), ("active", 2), ("archive", 1)])
        self.assertEqual(read, [B1, B2, B3, B4])
        self.assertEqual(self.sleep.call_args_list, [call(0.5)] + [call(1.5)] * 3)     # 1.5 s between requests
        self.assertEqual(ali._last_call, NOW)
        self.log.info.assert_called_once_with("ali_orders %r: %d found, %d scanned, %d fetched", None, 4, 4, 4)
        c = self.cached()
        self.assertEqual(c["ali:live"], {"at": NOW, "active": [[B1, "Ожидает получения", "1 234,56 ₽", ["1005001"]],
                                                               [B2, "Отправлен", "500 ₽", ["1005002"]]]})
        self.assertEqual(c["ali:list:archive"], {"at": NOW, "ids": [[B3, "Завершён", "990 ₽", ["1005003"]],
                                                                    [B4, "", "", ["1005004", "1005005"]],
                                                                    [B2, "Получен", "500 ₽", ["1005002"]]]})
        self.assertEqual(c["ali:" + B1], {"id": B1, "date": "1 октября 2026", "at": NOW,
                                          "products": ALI_DETAILS[B1]["products"]})
        self.assertNotIn("at", c["ali:" + B3])
        self.assertNotIn("ali:" + B4, c)                  # nothing read: asked again next time
        self.assertEqual(len(c), 5)

    def test_second_call_asks_only_for_the_unread_order(self):
        first, _, _ = self.ali_orders()
        out, pages, read = self.ali_orders()
        self.assertEqual((out, pages, read), (first, [], [B4]))

    def test_query_limit_and_cap(self):
        out, _, read = self.ali_orders(query="паяльник | жало", limit=1)
        self.assertEqual(out, "\n".join(["AliExpress: заказы с «паяльник | жало» в названии — найдено 1, "
                                         "просмотрено заказов 1", HEAD, ALI_ROWS[0]]))
        self.assertEqual(read, [B1])
        out, _, read = self.ali_orders(query="флюс", max_new=0)
        self.assertEqual(out, "AliExpress: заказы с «флюс» в названии — найдено 0, просмотрено заказов 1" + CAPPED
                         + "\n(ничего)")
        self.assertEqual(read, [])

    def test_no_break_spaces_in_the_total_become_plain(self):
        lists = {**ALI_LISTS, ("active", 1): ali_page(ali_order(B1, "1\xa0234,56\xa0₽", "1005001", status="Ожидает получения"),
                                                      more=True)}
        out, _, _ = self.ali_orders(lists=lists, query="паяльник")
        self.assertEqual(out.splitlines()[2:], [ALI_ROWS[0]])

    def test_orders_cached_before_dates_were_kept_apart(self):
        self.seed({"ali:live": {"at": NOW - 60, "active": []},
                   "ali:list:archive": {"at": NOW - 60, "ids": [[B3, "Завершён", "", ["1005003"]]]},
                   "ali:" + B3: {"id": B3, "when": "5 мая 2026 · Завершён", "total": "990 ₽",
                                 "products": [{"title": "Флюс", "url": "https://aliexpress.ru/item/1005003.html"}]}})
        out, pages, read = self.ali_orders()
        self.assertEqual(out.splitlines()[2:], [f"{B3}\t5 мая 2026 · Завершён\t990 ₽\tФлюс\t\t\thttps://aliexpress.ru/item/1005003.html"])
        self.assertEqual((pages, read), ([], []))

    def test_saved_archive_is_refreshed_from_the_top(self):
        K1, K2, K3, N1 = "8000000000000011", "8000000000000012", "8000000000000013", "8000000000000014"
        known = [[k, "Завершён", "1 ₽", []] for k in (K1, K2, K3)]
        self.seed({"ali:live": {"at": NOW - orders.LIVE_TTL, "active": []}, "ali:list:archive": {"at": 0, "ids": known},
                   **{"ali:" + k: {"id": k, "date": "", "products": [{"title": "старый"}]} for k in (K1, K2, K3)}})
        lists = {("active", 1): None,           # the site answered nothing
                 ("archive", 1): ali_page(ali_order(N1, "2 ₽", "1005014", status="Завершён"),
                                          ali_order(K1, "1 ₽", status="Завершён"), more=True),
                 ("archive", 2): ali_page(ali_order(K2, "1 ₽", status="Завершён"), more=True)}
        out, pages, read = self.ali_orders(lists=lists, dets={N1: ali_detail("", "Новое", "1005014")})
        self.assertEqual((pages, read), ([("active", 1), ("archive", 1), ("archive", 2)], [N1]))
        self.assertEqual(self.cached()["ali:list:archive"],
                         {"at": NOW, "ids": [[N1, "Завершён", "2 ₽", ["1005014"]]] + known})
        self.assertEqual(self.cached()["ali:live"], {"at": NOW, "active": []})
        self.assertTrue(out.startswith("AliExpress: заказы — найдено 4, просмотрено заказов 4\n"))

    def test_corrupt_cache_counts_as_empty(self):
        self.file.parent.mkdir()
        self.file.write_text("{not json", encoding="utf-8")
        out, pages, _ = self.ali_orders()
        self.assertEqual(len(pages), 3)
        self.assertEqual(len(self.cached()), 5)


class WalkTests(unittest.TestCase):
    def test_without_a_saved_list_every_page_is_read(self):
        self.assertEqual(orders._walk(iter([[(1,)], [(1,), (2,)], []])), [(1,), (1,), (2,)])

    def test_stops_at_the_first_page_with_nothing_new(self):
        pages = iter([[(5,), (4,)], [(3,), (2,)], [(1,)]])
        self.assertEqual(orders._walk(pages, [(3,), (2,), (1,), (0,)]), [(5,), (4,), (3,), (2,), (1,), (0,)])
        self.assertEqual(next(pages), [(1,)])           # the page after it is not requested


if __name__ == "__main__":
    unittest.main()
