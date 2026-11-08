"""The shared request budget: slots spaced by the site's gap, caps per window, stops after a block, the texts that
explain a refusal. A temp database and a fake clock; no browser.  Run: .venv/bin/python -B -m unittest -v test_pace"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pace

T0 = time.mktime((2026, 11, 8, 15, 0, 0, 0, 0, -1))      # 15:00:00 local


class Clock:
    """pace's clock and sleep: sleeping moves the clock."""
    def __init__(self, t=T0):
        self.t, self.slept = t, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


class PaceTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.clock = Clock()
        for p in (patch.object(pace, "OFF", False), patch.object(pace, "DB", Path(d.name) / "pace.sqlite"), patch.object(pace, "_now", self.clock.now),
                  patch.object(pace, "_sleep", self.clock.sleep)):
            p.start()
            self.addCleanup(p.stop)

    def burst(self, site, n, kind="api"):
        for _ in range(n):
            pace.acquire(site, kind)


class SlotTests(PaceTest):
    def test_the_site_s_gap_between_requests(self):
        pace.acquire("ozon")
        pace.acquire("ozon")
        pace.acquire("ozon", "page")
        self.assertEqual(self.clock.slept, [1.5, 4.0])       # api after api waits its gap; a page load its own

    def test_two_processes_get_two_slots(self):
        # the slot is written before the sleep: a second caller at the same moment queues behind it
        self.assertEqual(pace._reserve("ozon", "api", 1), 0)
        self.assertEqual(pace._reserve("ozon", "api", 1), 1.5)
        self.assertEqual(pace._reserve("ozon", "api", 1), 3.0)

    def test_sites_do_not_wait_for_each_other(self):
        pace.acquire("ozon")
        pace.acquire("wb")
        self.assertEqual(self.clock.slept, [])

    def test_a_full_window_waits_until_it_has_room(self):
        p = pace.Policy(gap={"page": 0, "api": 0}, caps=((60, 3),), cool=pace.DEFAULT.cool)
        with patch.dict(pace.POLICY, {"ozon": p}):
            self.burst("ozon", 3)
            self.clock.t += 50
            pace.acquire("ozon")
        self.assertEqual(self.clock.slept, [10.0])           # the oldest of the three leaves the minute at +60

    def test_a_full_window_far_off_is_refused_and_takes_no_slot(self):
        p = pace.Policy(gap={"page": 0, "api": 0}, caps=((600, 2),), cool=pace.DEFAULT.cool)
        with patch.dict(pace.POLICY, {"ozon": p}):
            self.burst("ozon", 2)
            with self.assertRaises(pace.Refused) as e:
                pace.acquire("ozon")
            self.assertEqual(str(e.exception),
                             "⏸ Ozon: предел запросов — 2 за 10 мин. Следующий не раньше 15:10:00 (через 10 мин). "
                             "Не повторяй раньше: займись другим магазином или подожди. Пределы общие для MCP, агентов и "
                             "скриптов и берегут IP пользователя от бана; состояние — shop_limits.")
            self.clock.t += 600
            pace.acquire("ozon")                             # the refusal took no slot
        self.assertEqual(self.clock.slept, [])

    def test_a_batch_counts_as_its_requests(self):
        p = pace.Policy(gap={"page": 0, "api": 0}, caps=((60, 4),), cool=pace.DEFAULT.cool)
        with patch.dict(pace.POLICY, {"avito": p}):
            pace.acquire("avito", cost=3)
            with self.assertRaises(pace.Refused):
                pace.acquire("avito", cost=2)
            pace.acquire("avito")

    def test_a_batch_larger_than_a_window_is_refused_even_on_a_quiet_site(self):
        with self.assertRaises(pace.Refused) as e:
            pace.acquire("avito", cost=17)
        self.assertEqual(str(e.exception), "⏸ Авито: 17 запросов за раз больше предела 16 за 1 мин. Уменьши пакет "
                                           "(у avito_search — shipping) и не повторяй его таким.")
        pace.acquire("avito", cost=16)                       # a search with its 15 delivery look-ups fits a quiet minute

    def test_old_requests_are_forgotten(self):
        self.burst("ozon", 3)
        self.clock.t += 2 * 3600
        pace.acquire("ozon")
        self.assertEqual(pace._count("ozon", 3600), 1)

    def test_a_short_wait_is_slept_too(self):
        p = pace.Policy(gap={"page": 0.5, "api": 0.5}, caps=pace.DEFAULT.caps, cool=pace.DEFAULT.cool)
        with patch.dict(pace.POLICY, {"ozon": p}):
            self.burst("ozon", 2)
        self.assertEqual(self.clock.slept, [0.5])

    def test_a_wait_of_exactly_the_most_is_still_taken(self):
        pace.acquire("samokat", "page")
        pace.acquire("samokat", "page")                      # its page gap is MAX_WAIT itself
        self.assertEqual(self.clock.slept, [pace.MAX_WAIT])

    def test_requests_of_the_last_hour_outlive_a_later_request(self):
        self.burst("ozon", 2)
        self.clock.t += 100
        pace.acquire("ozon")
        self.assertEqual(pace._count("ozon", 3600), 3)
        self.clock.t += 3590 - 100                           # the first is 59 min 50 s old: still in the hour
        pace.acquire("ozon")
        self.assertEqual(pace._count("ozon", 3600), 4)

    def test_an_unknown_site_gets_the_default(self):
        self.assertIs(pace.policy("new-site"), pace.DEFAULT)


class BlockTests(PaceTest):
    def test_a_block_stops_every_request_and_says_why(self):
        refusal = pace.blocked("perekrestok", "ban", "«Проблемы со связью» (ServicePipe)")
        self.assertIsInstance(refusal, pace.Refused)
        with self.assertRaises(pace.Refused) as e:
            pace.acquire("perekrestok")
        self.assertEqual(str(e.exception), str(refusal))
        self.assertEqual(str(e.exception),
                         "⏸ Перекрёсток: блокировка по IP — «Проблемы со связью» (ServicePipe), с 15:00. Запросы к сайту "
                         "остановлены до 21:00 (ещё 6 ч 0 мин) для всех: MCP, агентов и скриптов. Не повторяй до этого времени. "
                         "Её не пройти, можно только ждать: займись другими магазинами, пользователю делать ничего не нужно.")

    def test_each_kind_says_what_to_do(self):
        self.assertIn("попроси пользователя пройти её во вкладке сайта (shop-chrome show), потом выполни "
                      "~/shop-mcp/shop-pace clear ym", str(pace.blocked("ym", "check", "капча Яндекса")))
        self.assertIn("сайт просит реже: подожди или займись другими магазинами", str(pace.blocked("avito", "throttle", "HTTP 439")))

    def test_the_block_ends_by_itself(self):
        pace.blocked("ym", "check", "капча")
        self.clock.t += pace.POLICY["ym"].cool["check"] + 1
        pace.acquire("ym")

    def test_a_second_block_within_a_day_lasts_twice_as_long(self):
        pace.blocked("ym", "check", "капча")
        self.clock.t += pace.POLICY["ym"].cool["check"] + 1
        pace.blocked("ym", "check", "капча")
        self.assertEqual(pace._block("ym")["until"] - self.clock.t, 2 * pace.POLICY["ym"].cool["check"])

    def test_a_block_on_one_site_leaves_another_s_block_alone(self):
        pace.blocked("perekrestok", "ban", "IP")
        self.clock.t += 60
        pace.blocked("ym", "check", "капча")
        self.assertEqual(pace._block("perekrestok")["kind"], "ban")

    def test_the_block_keeps_what_led_to_it(self):
        self.burst("perekrestok", 3)
        pace.blocked("perekrestok", "check", "ServicePipe")
        b = pace._block("perekrestok")
        self.assertEqual((b["n1"], b["n10"], b["n60"]), (3, 3, 3))   # the lever to set the caps from real blocks

    def test_clear_lifts_a_check_but_not_a_ban(self):
        pace.blocked("ym", "check", "капча")
        self.assertEqual(pace.clear("ym"), "Яндекс Маркет: остановка снята")
        pace.acquire("ym")
        pace.blocked("perekrestok", "ban", "IP")
        self.assertTrue(pace.clear("perekrestok").startswith("Перекрёсток: это блокировка по IP, её снимает только время"))
        with self.assertRaises(pace.Refused):
            pace.acquire("perekrestok")
        self.assertEqual(pace.clear("perekrestok", ban=True), "Перекрёсток: остановка снята")
        pace.acquire("perekrestok")
        self.assertEqual(pace.clear("perekrestok"), "Перекрёсток: остановки нет")


PAGE = {"url": "https://www.perekrestok.ru/", "title": "Перекрёсток", "text": "Каталог", "size": 50000, "slider": False}


class PageSignTests(PaceTest):
    def test_block_pages_are_recognised(self):
        cases = [({**PAGE, "url": "https://samokat.ru/xpvnsulc/?a=1"}, "samokat", "check", "проверка ServicePipe"),
                 ({**PAGE, "url": "https://market.yandex.ru/showcaptcha?x"}, "ym", "check", "капча Яндекса"),
                 ({**PAGE, "text": "Проблемы со связью.\nПроверьте настройки интернета и VPN", "size": 300}, "perekrestok", "ban",
                  "«Проблемы со связью» (ServicePipe)"),
                 ({**PAGE, "title": "Доступ ограничен: проблема с IP", "size": 400}, "avito", "throttle", "«Доступ ограничен» (Авито)"),
                 ({**PAGE, "slider": True}, "ali", "check", "слайдер AliExpress")]
        for probe, site, kind, what in cases:
            with self.subTest(site):
                with self.assertRaises(pace.Refused):
                    pace.check_page(site, probe)
                self.assertEqual((pace._block(site)["kind"], pace._block(site)["detail"]), (kind, what))

    def test_a_long_page_that_mentions_the_words_is_no_block(self):
        pace.check_page("perekrestok", {**PAGE, "text": "Проблемы со связью у курьера, пишут в отзывах", "size": pace.SHORT})
        pace.check_page("perekrestok", PAGE)
        pace.check_page("perekrestok", None)                 # the page could not be read: say nothing
        self.assertIsNone(pace._block("perekrestok"))


class SpanTests(unittest.TestCase):
    def test_seconds_minutes_and_hours(self):
        self.assertEqual([pace._span(s) for s in (0, 59.4, 60, 3599, 3600, 7260)], ["0 с", "59 с", "1 мин", "59 мин", "1 ч 0 мин", "2 ч 1 мин"])


class StatusTests(PaceTest):
    def test_counts_against_the_caps_and_the_blocks(self):
        self.burst("ozon", 2)
        pace.blocked("perekrestok", "ban", "«Проблемы со связью»")
        lines = pace.status().splitlines()
        self.assertEqual(lines[0], "запросы к магазинам за 1 / 10 / 60 мин и их пределы (общие для всех процессов); ⏸ — остановлены")
        self.assertIn("Ozon\t2/30\t2/150\t2/600\t", lines)
        self.assertIn("Перекрёсток\t0/15\t0/60\t0/200\t⏸ блокировка по IP до 21:00 (ещё 6 ч 0 мин): «Проблемы со связью»", lines)


if __name__ == "__main__":
    unittest.main()
