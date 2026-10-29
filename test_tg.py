"""Telegram notifications: what tg.send and tg.setup ask the Bot API and write to telegram.json.
No requests: the Bot API is a mock, telegram.json lives in a temp dir.  Run: .venv/bin/python -B -m unittest -v test_tg"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import tg

API = "https://api.telegram.org/bot123:TEST/"


class TgTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.conf = Path(tmp.name) / "telegram.json"
        self.updates, self.asked = [], []        # what getUpdates answers; (url, form, timeout) of every request

        def urlopen(url, data, timeout):
            self.asked.append((url, parse_qs(data.decode()), timeout))
            return io.BytesIO(json.dumps({"ok": True, "result": self.updates if url.endswith("/getUpdates") else {"message_id": 1}}).encode())
        for p in (patch.object(tg, "CONF", self.conf), patch.object(tg.urllib.request, "urlopen", side_effect=urlopen)):
            p.start()
            self.addCleanup(p.stop)

    def sent(self):
        return [(form["chat_id"], form["text"]) for url, form, _ in self.asked if url == API + "sendMessage"]

    def test_send(self):
        self.conf.write_text(json.dumps({"token": "123:TEST", "chat_id": 42}))
        tg.send("<b>Новое</b>\n\nВелосипед — 5 000 ₽")
        self.assertEqual(self.asked, [(API + "sendMessage", {"chat_id": ["42"], "text": ["<b>Новое</b>\n\nВелосипед — 5 000 ₽"],
                                                             "parse_mode": ["HTML"], "disable_web_page_preview": ["true"]}, 20)])

    def test_long_text_is_split_on_blank_lines(self):
        self.conf.write_text(json.dumps({"token": "123:TEST", "chat_id": 42}))
        a, b, c, d = "a" * 2000, "b" * 1998, "c" * 1999, "d" * 2000   # a, blank line, b: the 4000 limit; c, blank line, d: one over
        tg.send(f"{a}\n\n{b}\n\n{c}\n\n{d}")
        self.assertEqual(self.sent(), [(["42"], [f"{a}\n\n{b}"]), (["42"], [c]), (["42"], [d])])

    def test_setup_saves_the_last_chat_and_says_hello(self):
        self.conf.write_text(json.dumps({"token": "123:TEST"}))
        self.updates = [{"update_id": 1, "message": {"chat": {"id": 101, "username": "first_test_user"}}},
                        {"update_id": 2, "my_chat_member": {"chat": {"id": 303}}},
                        {"update_id": 3, "message": {"chat": {"id": 202, "username": "second_test_user"}}},
                        {"update_id": 4, "message": {"chat": {"id": 404, "username": "test_user"}}}]
        out = io.StringIO()
        with redirect_stdout(out):
            tg.setup()
        self.assertEqual(json.loads(self.conf.read_text()), {"token": "123:TEST", "chat_id": 404})
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.asked[0], (API + "getUpdates", {}, 20))
        self.assertEqual(self.sent(), [(["404"], ["Бот мониторинга Авито подключён ✅"])])
        self.assertEqual(out.getvalue(), "chat_id 404 (@test_user) saved, test message sent\n")

    def test_setup_before_anyone_wrote_to_the_bot(self):
        self.conf.write_text(json.dumps({"token": "123:TEST"}))
        self.updates = [{"update_id": 2, "my_chat_member": {"chat": {"id": 303}}}]
        with self.assertRaises(SystemExit) as e:
            tg.setup()
        self.assertEqual(e.exception.code, "No messages yet: send /start to the bot and run again.")
        self.assertEqual(json.loads(self.conf.read_text()), {"token": "123:TEST"})
        self.assertEqual(self.sent(), [])


if __name__ == "__main__":
    unittest.main()
