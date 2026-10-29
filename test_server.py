"""server.py without the MCP transport: logged() around every tool (time, answer size, warnings, errors,
the stale-server note), the reload of edited modules before each call, every tool's hand-off to its site
function, and shop_status.
No requests to shops, no Chrome, nothing written to logs/.  Run: .venv/bin/python -B -m unittest -v test_server"""
import asyncio
import inspect
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, create_autospec, patch

import server


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class LoggedTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.log = MagicMock()
        self.reload = MagicMock()
        for p in (patch.object(server, "time", self.clock), patch.object(server, "log", self.log),
                  patch.object(server, "_reload_changed", self.reload)):
            self.addCleanup(p.stop)
            p.start()

    def tool(self, answer):
        """A tool that takes 2.5 s and answers with answer (raises it, if it is an exception)."""
        def wb_search(query: str = "", limit: int = 30) -> str:
            """Поиск на Wildberries."""
            self.clock.sleep(2.5)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return server.logged(wb_search)

    def test_answer_is_returned_and_logged_with_its_time_and_size(self):
        out = self.tool("цена\tназвание\n100\tчай\n200\tкофе")("чай", limit=2)
        self.assertEqual(out, "цена\tназвание\n100\tчай\n200\tкофе")
        self.log.log.assert_called_once_with(20, "%s ok in %.1f s, %d lines: %s",
                                             "wb_search ('чай',){'limit': 2}", 2.5, 3, "цена\tназвание")
        self.log.exception.assert_not_called()

    def test_call_without_arguments_is_named_plainly(self):
        self.tool("ok")()
        self.assertEqual(self.log.log.call_args.args[2], "wb_search {}")

    def test_only_the_first_150_characters_of_the_first_line_are_logged(self):
        self.tool("x" * 200 + "\nsecond")()
        self.assertEqual(self.log.log.call_args.args[-1], "x" * 150)

    def test_bot_checks_and_blocks_are_logged_as_warnings(self):
        for text in ("⚠️ проверка на бота", "Ozon включил блокировку", "сработала проверка Авито"):
            with self.subTest(text):
                self.log.reset_mock()
                self.tool("итого\n" + text)()
                self.assertEqual(self.log.log.call_args.args[0], 30)

    def test_failure_is_logged_with_its_time_and_raised(self):
        with self.assertRaisesRegex(ValueError, "boom"):
            self.tool(ValueError("boom"))("чай")
        self.log.exception.assert_called_once_with("%s failed in %.1f s", "wb_search ('чай',){}", 2.5)
        self.log.log.assert_not_called()

    def test_edited_modules_are_reloaded_before_the_tool_runs(self):
        order = []
        self.reload.side_effect = lambda: order.append("reload")
        server.logged(lambda: order.append("tool") or "ok")()
        self.assertEqual(order, ["reload", "tool"])

    def test_module_that_no_longer_loads_fails_the_call(self):
        self.reload.side_effect = SyntaxError("invalid syntax (ozon.py, line 3)")
        tool = MagicMock(__name__="ozon_item")
        with self.assertRaises(SyntaxError):
            server.logged(tool)()
        tool.assert_not_called()
        self.assertEqual(self.log.exception.call_args.args, ("%s failed in %.1f s", "ozon_item {}", 0.0))

    def test_stale_server_says_so_before_the_answer(self):
        with patch.object(server, "_STARTED", 0):
            out = self.tool("цена\n100")()
        self.assertEqual(out, server.STALE + "цена\n100")
        self.assertTrue(self.log.log.call_args.args[-1].startswith("⚠️ Сервер shop запущен со старой версией"))
        self.assertEqual(self.log.log.call_args.args[0], 30)

    def test_fresh_server_answers_as_is(self):
        self.assertEqual(self.tool("цена")(), "цена")

    def test_pictures_answer_is_logged_by_its_text_and_returned_as_is(self):
        picture = object()
        answer = ["картинок: 1 из 1\n/cache/images/a.jpg\t10x10\thttps://a.test/a.jpg", picture]
        with patch.object(server, "_STARTED", 0):      # the stale note is only added to text answers
            out = self.tool(answer)()
        self.assertIs(out, answer)
        self.assertEqual(out, ["картинок: 1 из 1\n/cache/images/a.jpg\t10x10\thttps://a.test/a.jpg", picture])
        self.assertEqual(self.log.log.call_args.args[-2:], (2, "картинок: 1 из 1"))

    def test_tool_keeps_its_name_signature_and_description(self):
        # FastMCP builds the tool's schema and description from these
        tool = self.tool("ok")
        self.assertEqual(tool.__name__, "wb_search")
        self.assertEqual(tool.__doc__, "Поиск на Wildberries.")
        self.assertEqual(str(inspect.signature(tool)), "(query: str = '', limit: int = 30) -> str")


class ReloadTests(unittest.TestCase):
    """_reload_changed on three stand-in modules in a temp dir; importlib.reload itself is a mock."""
    NAMES = ("t_cdp", "t_ozon", "t_server_dep")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.files = {}
        modules = {}
        for i, name in enumerate(self.NAMES):
            f = Path(tmp.name) / f"{name}.py"
            f.write_text("")
            os.utime(f, (100 + i, 100 + i))
            self.files[name] = f
            modules[name] = types.ModuleType(name)
            modules[name].__file__ = str(f)
        self.mtimes = {name: 100 + i for i, name in enumerate(self.NAMES)}
        self.reload = MagicMock()
        self.log = MagicMock()
        for p in (patch.dict(sys.modules, modules), patch.object(server, "_RELOADABLE", self.NAMES),
                  patch.object(server, "_mtimes", self.mtimes), patch.object(server.importlib, "reload", self.reload),
                  patch.object(server, "log", self.log)):
            self.addCleanup(p.stop)
            p.start()

    def touch(self, name, mtime):
        os.utime(self.files[name], (mtime, mtime))

    def reloaded(self):
        return [c.args[0].__name__ for c in self.reload.call_args_list]

    def test_unchanged_modules_stay(self):
        server._reload_changed()
        self.reload.assert_not_called()
        self.log.info.assert_not_called()

    def test_edited_module_and_every_one_after_it_are_reloaded_in_order(self):
        self.touch("t_ozon", 500)
        server._reload_changed()
        self.assertEqual(self.reloaded(), ["t_ozon", "t_server_dep"])
        self.assertEqual(self.log.info.call_args_list, [call("reloaded %s.py", "t_ozon"), call("reloaded %s.py", "t_server_dep")])

    def test_reloaded_modules_are_not_reloaded_again(self):
        self.touch("t_cdp", 500)
        server._reload_changed()
        server._reload_changed()
        self.assertEqual(self.reloaded(), list(self.NAMES))
        self.assertEqual(self.mtimes, {"t_cdp": 500, "t_ozon": 101, "t_server_dep": 102})

    def test_module_that_fails_to_load_is_tried_again_next_call(self):
        self.touch("t_ozon", 500)
        self.reload.side_effect = [SyntaxError("invalid syntax"), None, None]
        with self.assertRaises(SyntaxError):
            server._reload_changed()
        server._reload_changed()                       # fixed: the next call reloads it and what follows
        self.assertEqual(self.reloaded(), ["t_ozon", "t_ozon", "t_server_dep"])
        self.assertEqual(self.mtimes["t_ozon"], 500)


class ToolTests(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(server, "log"), patch.object(server, "_reload_changed")):
            self.addCleanup(p.stop)
            p.start()

    def test_shop_status_is_the_report_of_shop_chrome_status(self):
        done = subprocess.CompletedProcess([], 1, "Chrome: не запущен\n", "uv: нет\n")
        with patch("subprocess.run", return_value=done) as run:
            self.assertEqual(server.shop_status(), "Chrome: не запущен\nuv: нет")
        run.assert_called_once_with([str(Path(server.__file__).parent / "shop-chrome"), "status"],
                                    capture_output=True, text=True, timeout=30)

    def test_shop_images_passes_the_links_and_returns_the_pictures(self):
        answer = ["картинок: 1 из 1", object()]
        with patch.object(server.images, "images", return_value=answer) as images:
            self.assertIs(server.shop_images(["https://a.lmcdn.ru/x.jpg"], max_side=512), answer)
        images.assert_called_once_with(["https://a.lmcdn.ru/x.jpg"], 512)

    SITES = ("ali", "avito", "goldapple", "grocery", "images", "lamoda", "messenger", "orders", "ozon", "reviews", "wb", "ym")
    SAMPLE = {str: lambda n, i: f"<{n}>", int: lambda n, i: 7000 + i, list[str]: lambda n, i: [f"<{n}>"]}

    def test_every_tool_hands_its_arguments_to_a_site_function_that_takes_them(self):
        # autospec: a site function whose parameters no longer match the tool's call raises TypeError here;
        # the tools' defaults are their site functions' defaults (113 of them on 2026-10-29), so the two cannot drift apart
        names = sorted(t.name for t in asyncio.run(server.mcp.list_tools()))
        self.assertGreater(len(names), 50)
        sites = {s: create_autospec(getattr(server, s)) for s in self.SITES}
        for name in names:
            if name == "shop_status":
                continue
            tool = getattr(server, name)
            args = {p.name: self.SAMPLE[p.annotation](p.name, i)       # values no default has
                    for i, p in enumerate(inspect.signature(tool).parameters.values()) if p.default is p.empty}
            for m in sites.values():
                m.reset_mock()
            with self.subTest(name), patch.multiple(server, **sites):
                out = tool(**args)
                called = [(s, c) for s, m in sites.items() for c in m.mock_calls if "(" not in c[0]]   # not logged() reading the answer
                self.assertEqual(len(called), 1, called)
                site, (fn, a, kw) = called[0]
                self.assertIs(out, getattr(sites[site], fn).return_value)
                for v in args.values():
                    self.assertIn(v, list(a) + list(kw.values()))
                # an argument left out of the tool reaches the site function as that function's own default
                own = inspect.signature(getattr(getattr(server, site), fn))
                for param, got in own.bind(*a, **kw).arguments.items():
                    default = own.parameters[param].default
                    if got not in args.values() and default is not inspect.Parameter.empty:
                        self.assertEqual(got, default, f"{name}: {site}.{fn}({param}=...)")


if __name__ == "__main__":
    unittest.main()
