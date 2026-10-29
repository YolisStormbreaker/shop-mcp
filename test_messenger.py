"""Avito messenger: what the messenger socket answers -> the chat list and a chat; what send() types and presses.
No requests to shops, nothing is sent: the tab is a mock.  Run: .venv/bin/python -B -m unittest -v test_messenger"""
import json
import unittest
from datetime import datetime
from unittest.mock import ANY, MagicMock, call, patch

import messenger

ME, SELLER = "uid-me", "uid-seller"
ITEM = "/sankt-peterburg/velosipedy/test_velosiped_1"
HEAD = "чат\tнепрочитан\tкогда\tсобеседник\tобъявление\tцена\tпоследнее сообщение\tобъявление (путь на avito.ru)"
INPUT = json.dumps(messenger.INPUT)
BUTTON = '[data-marker="messenger-button/button"]'


def at(day, hour, minute):
    """A local time in October 2026 the way the messenger sends it: 100 ns since the epoch."""
    return int(datetime(2026, 10, day, hour, minute).timestamp()) * 10**7


def ok(result):
    return {"result": result}


def avito_tab(rpc, host="www.avito.ru", js=None):
    """A mocked Avito tab. rpc: method -> [socket answers, consumed in order]; every socket request is kept
    in tab.sent as (calls, timeout). Other expressions go to js."""
    tab = MagicMock()
    tab.sent = []

    def evaluate(expr, timeout=60):
        if expr.startswith(messenger.RPC_JS):
            socket, calls = json.loads("[" + expr[len(messenger.RPC_JS) + 1:-1] + "]")
            assert socket == messenger.SOCKET, socket
            tab.sent.append((calls, timeout))
            return {"out": [rpc[method].pop(0) for method, _ in calls]}
        if expr == "location.host":
            return host
        return js(expr) if js else None
    tab.js.side_effect = evaluate
    return tab


def run(fn, tab, *args, **kw):
    with patch.object(messenger, "tab_for", return_value=tab) as tab_for, patch.object(messenger, "log") as log, \
            patch.object(messenger.time, "sleep") as sleep:
        got = fn(*args, **kw)
    tab_for.assert_called_once_with("avito.ru")
    tab.close.assert_called_once()
    return got, log, sleep


def channel(cid, updated, read=True, last=None):
    return {"channelId": cid, "updated": updated, "isRead": read, "lastMessage": last,
            "info": {"name": "Продавец"}, "context": {"value": {"title": "Велосипед", "priceString": "5 000 ₽", "urlPath": ITEM}}}


def ids(out):
    return [line.split("\t")[0] for line in out.split("\n")[1:] if "\t" in line]


LONG = "Можно посмотреть сегодня? " * 10
CHATS = [
    {"channelId": "u2i-1", "updated": at(6, 14, 30), "isRead": False, "info": {"name": "Продавец"},
     "context": {"value": {"title": "Велосипед", "priceString": "5 000 ₽", "urlPath": ITEM}},
     "lastMessage": {"type": "text", "fromUid": ME, "uid": ME, "body": {"text": "Ещё продаётся?"}}},
    {"channelId": "u2i-2", "updated": at(5, 9, 5), "isRead": True, "info": {"name": "Покупатель"},
     "context": {"value": {"title": "Шкаф", "priceString": "1 200 ₽"}},
     "lastMessage": {"type": "text", "fromUid": SELLER, "uid": ME, "body": {"text": LONG}}},
    {"channelId": "u2i-3", "updated": at(4, 23, 59), "isRead": True, "info": {"name": "Покупатель"},
     "lastMessage": {"type": "system", "uid": ME, "body": {"text": "Покупатель  забронировал\nтовар"}}},
    {"channelId": "u2i-4", "updated": at(1, 0, 0)},
]


class ChatsTests(unittest.TestCase):
    def test_one_page(self):
        tab = avito_tab({"avito.getChats.v5": [ok({"channels": CHATS, "hasMore": False})]})
        out, _, _ = run(messenger.chats, tab)
        self.assertEqual(tab.sent, [([["avito.getChats.v5", {"limit": 30}]], 46)])
        tab.goto.assert_not_called()
        self.assertEqual(out, "\n".join([
            HEAD,
            f"u2i-1\t●\t06.10 14:30\tПродавец\tВелосипед\t5 000 ₽\tя: Ещё продаётся?\t{ITEM}",
            "u2i-2\t\t05.10 09:05\tПокупатель\tШкаф\t1 200 ₽\tПокупатель: " + "Можно посмотреть сегодня? " * 7 + "Можно \t",
            "u2i-3\t\t04.10 23:59\tПокупатель\t\t\tПокупатель забронировал товар\t",
            "u2i-4\t●\t01.10 00:00\t\t\t\t\t"]))

    def test_pages_until_the_limit(self):
        page1 = [channel("u2i-a", 100), channel("u2i-b", 90)]
        page2 = [channel("u2i-b", 90), channel("u2i-c", 80), channel("u2i-d", 70)]   # the boundary chat comes again
        tab = avito_tab({"avito.getChats.v5": [ok({"channels": page1, "hasMore": True}), ok({"channels": page2, "hasMore": True})]})
        out, _, _ = run(messenger.chats, tab, limit=3)
        self.assertEqual([calls for calls, _ in tab.sent], [[["avito.getChats.v5", {"limit": 30}]],
                                                           [["avito.getChats.v5", {"limit": 30, "offsetTimestamp": 90}]]])
        self.assertEqual(ids(out), ["u2i-a", "u2i-b", "u2i-c"])
        self.assertEqual(out.split("\n")[-1], "следующая страница: before=80")

    def test_a_full_last_page_still_offers_the_next(self):
        tab = avito_tab({"avito.getChats.v5": [ok({"channels": [channel("u2i-a", 100), channel("u2i-b", 90)], "hasMore": False})]})
        out, _, _ = run(messenger.chats, tab, limit=2)
        self.assertEqual(ids(out), ["u2i-a", "u2i-b"])
        self.assertEqual(out.split("\n")[-1], "следующая страница: before=90")

    def test_unread_before_a_time(self):
        page1 = [channel("u2i-edge", 500, read=False), channel("u2i-read", 400), channel("u2i-new", 300, read=False)]
        page2 = [channel("u2i-old", 200, read=False), channel("u2i-old-read", 100)]
        tab = avito_tab({"avito.getChats.v5": [ok({"channels": page1, "hasMore": True}), ok({"channels": page2, "hasMore": False})]})
        out, _, _ = run(messenger.chats, tab, unread_only=True, before="500")
        self.assertEqual([calls[0][1] for calls, _ in tab.sent], [{"limit": 30, "offsetTimestamp": 500},
                                                                 {"limit": 30, "offsetTimestamp": 300}])
        self.assertEqual(ids(out), ["u2i-new", "u2i-old"])
        self.assertEqual(out.split("\n")[-1].split("\t")[:2], ["u2i-old", "●"])

    def test_no_chats(self):
        tab = avito_tab({"avito.getChats.v5": [ok({"hasMore": True})]})
        self.assertEqual(run(messenger.chats, tab)[0], HEAD + "\n(пусто)")

    def test_zero_limit_asks_nothing(self):
        tab = avito_tab({})
        self.assertEqual(run(messenger.chats, tab, limit=0)[0], HEAD + "\n(пусто)")
        self.assertEqual(tab.sent, [])

    def test_socket_error_is_raised_and_the_tab_closed(self):
        for error, text in (({"message": "no session"}, "Авито avito.getChats.v5: no session"),
                            ({"code": 500}, "Авито avito.getChats.v5: {'code': 500}")):
            with self.subTest(error=error):
                tab = avito_tab({"avito.getChats.v5": [{"error": error}]})
                with self.assertRaises(RuntimeError) as e:
                    run(messenger.chats, tab)
                self.assertEqual(str(e.exception), text)
                tab.close.assert_called_once()

    def test_the_error_is_logged(self):
        tab = avito_tab({"avito.getChats.v5": [{"error": {"message": "no session"}}]})
        with patch.object(messenger, "tab_for", return_value=tab), patch.object(messenger, "log") as log:
            self.assertRaises(RuntimeError, messenger.chats)
        log.warning.assert_called_once_with("avito rpc %s %s: %s", "avito.getChats.v5", {"limit": 30}, {"message": "no session"})

    def test_a_blank_tab_goes_to_avito_first(self):
        for host in (None, "", "example.com"):
            with self.subTest(host=host):
                tab = avito_tab({"avito.getChats.v5": [ok({})]}, host=host)
                run(messenger.chats, tab)
                tab.goto.assert_called_once_with("https://www.avito.ru/profile/messenger", "avito", wait_js="document.body")


# one chat's history, newest first as the socket sends it; between them every kind of message text
HISTORY = [
    {"type": "image", "created": 0},
    {"type": "text", "created": at(6, 12, 3), "fromUid": SELLER, "uid": ME, "body": {"text": "Сообщение не поддерживается"}},
    {"type": "text", "created": at(6, 12, 2), "fromUid": SELLER, "uid": ME,
     "body": {"text": "Сообщение не поддерживается в этой версии"}, "preview": {"text": "Фото"}},
    {"type": "text", "created": at(6, 12, 1), "fromUid": SELLER, "uid": ME,
     "body": {"chunks": [{"value": {"text": "Адрес:"}}, {"type": "link"}, {"value": {"text": "ул. Тестовая, 1"}}]}},
    {"type": "system", "created": at(6, 11, 0), "uid": ME, "body": {}, "preview": {"text": "Покупатель забронировал товар"}},
    {"type": "text", "created": at(6, 10, 30), "fromUid": ME, "uid": ME, "body": {"text": "удалено"}, "isDeleted": True},
    {"type": "text", "created": at(6, 10, 15), "fromUid": ME, "uid": ME, "body": {"text": "Можно забрать завтра?"}},
    {"type": "text", "created": at(6, 10, 0), "fromUid": SELLER, "uid": ME, "body": {"text": " Здравствуйте!  Да,\n продаётся "}},
]
INFO = {"info": {"name": "Продавец"}, "inputState": {"isDisabled": True},
        "context": {"value": {"title": "Велосипед", "priceString": "5 000 ₽", "urlPath": ITEM}}}


class ChatTests(unittest.TestCase):
    def test_whole_chat(self):
        tab = avito_tab({"avito.getChatById.v3": [ok(INFO)], "messenger.history.v2": [ok({"items": HISTORY})]})
        out, _, _ = run(messenger.chat, tab, " https://www.avito.ru/profile/messenger/channel/u2i-chat1?context=x ", limit=8, offset=10)
        self.assertEqual(tab.sent, [([["avito.getChatById.v3", {"channelId": "u2i-chat1"}],
                                      ["messenger.history.v2", {"channelId": "u2i-chat1", "limit": 8, "offset": 10}]], 62)])
        self.assertEqual(out, "\n".join([
            f"чат u2i-chat1 с Продавец · Велосипед · 5 000 ₽ · https://www.avito.ru{ITEM}",
            "⛔ писать в этот чат нельзя",
            "06.10 10:00\tПродавец\tЗдравствуйте! Да, продаётся",
            "06.10 10:15\tя\tМожно забрать завтра?",
            "06.10 11:00\tАвито\tПокупатель забронировал товар",
            "06.10 12:01\tПродавец\tАдрес: ул. Тестовая, 1",
            "06.10 12:02\tПродавец\tФото",
            "06.10 12:03\tПродавец\tСообщение не поддерживается",
            "\tПродавец\t[image]",
            "(есть сообщения раньше: offset=18)"]))

    def test_chat_without_a_listing(self):
        tab = avito_tab({"avito.getChatById.v3": [ok({"info": {"name": "Покупатель"}, "context": {"value": {"title": "Шкаф"}}})],
                         "messenger.history.v2": [ok({"items": HISTORY[-1:]})]})
        out, _, _ = run(messenger.chat, tab, "u2i-chat2")
        self.assertEqual(tab.sent[0][0][1], ["messenger.history.v2", {"channelId": "u2i-chat2", "limit": 30, "offset": 0}])
        self.assertEqual(out, "чат u2i-chat2 с Покупатель\n06.10 10:00\tПокупатель\tЗдравствуйте! Да, продаётся")

    def test_empty_chat(self):
        tab = avito_tab({"avito.getChatById.v3": [ok({})], "messenger.history.v2": [ok({})]})
        self.assertEqual(run(messenger.chat, tab, "u2i-chat3/")[0], "чат u2i-chat3 с ")


ENTER = [call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13,
              nativeVirtualKeyCode=13, text="\r"),
         call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)]
FOCUS = [call("Page.bringToFront"), call("Emulation.setFocusEmulationEnabled", enabled=True)]
UNFOCUS = call("Emulation.setFocusEmulationEnabled", enabled=False)
TEXT = "Здравствуйте!\nЕщё продаётся?"
MINE = {"type": "text", "fromUid": ME, "uid": ME, "body": {"text": "Здравствуйте! Ещё продаётся?"}}
THEIRS = {"type": "text", "fromUid": SELLER, "uid": ME, "body": {"text": "Здравствуйте! Ещё продаётся?"}}


def send_tab(rpc, box=(True,), value=None, button=(640.5, 360.0), hrefs=(), h1=""):
    """The tab send() drives. The reply box shows up on the polls given by box; it then holds what Input.insertText
    typed (or value); the listing's biggest write button is at button; location.href walks through hrefs."""
    box, hrefs, typed = list(box), list(hrefs), []

    def js(expr):
        if expr == f"!!document.querySelector({INPUT})":
            return box.pop(0)
        if expr == f"document.querySelector({INPUT}).value":
            return typed[-1] if value is None else value
        if expr == "location.href":
            return hrefs.pop(0)
        if "getBoundingClientRect" in expr and json.dumps(BUTTON) in expr:
            return button
        if expr == "document.querySelector('h1')?.textContent":
            return h1
        assert expr == f"document.querySelector({INPUT}).focus()", expr
    tab = avito_tab(rpc, js=js)
    tab.call.side_effect = lambda method, **params: typed.append(params["text"]) if method == "Input.insertText" else None
    tab.typed = typed
    return tab


def history(*items):
    return ok({"items": list(items)})


class SendTests(unittest.TestCase):
    def test_to_a_chat(self):
        tab = send_tab({"messenger.history.v2": [history(THEIRS), history(MINE, THEIRS)]}, box=(False, False, True))
        out, _, sleep = run(messenger.send, tab, f"  {TEXT}\n", chat_id="https://www.avito.ru/profile/messenger/channel/u2i-chat1")
        self.assertEqual(out, "отправлено в чат u2i-chat1")
        tab.goto.assert_called_once_with("https://www.avito.ru/profile/messenger/channel/u2i-chat1", "avito",
                                         wait_js=f"document.querySelector({INPUT})")
        tab.click.assert_called_once_with(messenger.INPUT)
        self.assertEqual(tab.call.call_args_list, FOCUS + [call("Input.insertText", text=TEXT)] + ENTER + [UNFOCUS])
        self.assertEqual([calls for calls, _ in tab.sent], [[["messenger.history.v2", {"channelId": "u2i-chat1", "limit": 5}]]] * 2)
        self.assertEqual(sleep.call_args_list, [call(0.5)] * 3 + [call(1)] * 2)

    def test_to_the_seller_found_among_the_chats(self):
        chats = [{"channelId": "u2i-other", "lastMessage": {**MINE, "body": {"text": "Другое"}}}, {"channelId": "u2i-empty"},
                 {"channelId": "u2i-new", "lastMessage": MINE}]
        tab = send_tab({"avito.getChats.v5": [ok({"channels": chats})], "messenger.history.v2": [history(MINE)]},
                       hrefs=["https://www.avito.ru" + ITEM])
        out, _, _ = run(messenger.send, tab, TEXT, item_url="https://www.avito.ru" + ITEM)
        self.assertEqual(out, "отправлено в чат u2i-new")
        tab.goto.assert_called_once_with("https://www.avito.ru" + ITEM, "avito",
                                         wait_js="document.querySelector('[data-marker=\"messenger-button/button\"]')")
        mouse = [call("Input.dispatchMouseEvent", type=t, x=640.5, y=360.0, button="left", clickCount=1)
                 for t in ("mouseMoved", "mousePressed", "mouseReleased")]
        self.assertEqual(tab.call.call_args_list, FOCUS + mouse + [call("Input.insertText", text=TEXT)] + ENTER + [UNFOCUS])
        self.assertEqual([calls for calls, _ in tab.sent], [[["avito.getChats.v5", {"limit": 5}]],
                                                           [["messenger.history.v2", {"channelId": "u2i-new", "limit": 5}]]])

    def test_to_the_seller_found_by_the_page_address(self):
        tab = send_tab({"avito.getChats.v5": [ok({})], "messenger.history.v2": [history(THEIRS), history(MINE)]},
                       hrefs=["https://www.avito.ru" + ITEM, "https://www.avito.ru/profile/messenger/channel/u2i-new?from=item"])
        out, _, _ = run(messenger.send, tab, TEXT, item_url="https://www.avito.ru" + ITEM)
        self.assertEqual(out, "отправлено в чат u2i-new")
        self.assertEqual([calls[0] for calls, _ in tab.sent], [["avito.getChats.v5", {"limit": 5}]]
                         + [["messenger.history.v2", {"channelId": "u2i-new", "limit": 5}]] * 2)

    def test_listing_without_a_write_button(self):
        tab = send_tab({}, button=None, h1="  Велосипед\n детский ")
        out, _, _ = run(messenger.send, tab, TEXT, item_url="https://www.avito.ru" + ITEM)
        self.assertEqual(out, "на странице объявления нет кнопки «Написать сообщение» (заголовок: «Велосипед детский») — ничего не отправлено")
        self.assertEqual(tab.call.call_args_list, FOCUS + [UNFOCUS])
        tab.click.assert_not_called()

    def test_no_reply_box(self):
        tab = send_tab({}, box=[False] * 20)
        out, _, sleep = run(messenger.send, tab, TEXT, chat_id="u2i-closed")
        self.assertEqual(out, "не нашёл поле ввода сообщения — ничего не отправлено. Чат закрыт или страница не загрузилась.")
        self.assertEqual(tab.call.call_args_list, FOCUS + [UNFOCUS])
        self.assertEqual(sleep.call_count, 20)

    def test_text_that_did_not_reach_the_box_is_not_sent(self):
        tab = send_tab({}, value="Здравствуйте!")
        with self.assertRaises(RuntimeError) as e:
            run(messenger.send, tab, TEXT, chat_id="u2i-chat1")
        self.assertEqual(str(e.exception), "текст не попал в поле ввода — сообщение не отправлено")
        self.assertEqual(tab.call.call_args_list, FOCUS + [call("Input.insertText", text=TEXT), UNFOCUS])
        tab.close.assert_called_once()

    def test_not_seen_in_the_chat(self):
        tab = send_tab({"messenger.history.v2": [history(THEIRS)] * 10})
        out, log, sleep = run(messenger.send, tab, TEXT, chat_id="u2i-chat1")
        self.assertEqual(out, "⚠️ Enter нажат, но в истории чата u2i-chat1 сообщения не видно. "
                              "Проверить через avito_chats / avito_chat, прежде чем отправлять ещё раз.")
        self.assertEqual(len(tab.sent), 10)
        self.assertEqual(sleep.call_args_list[-10:], [call(1)] * 10)
        log.warning.assert_called_once_with("avito send: message not seen in history, chat %s", "u2i-chat1")

    def failing_checks(self, n, rpc):
        """send_tab whose first n socket requests fail, as on a dropped session or a socket timeout."""
        tab = send_tab(rpc)
        evaluate, left = tab.js.side_effect, [n]

        def js(expr, timeout=60):
            if expr.startswith(messenger.RPC_JS) and left[0]:
                left[0] -= 1
                raise RuntimeError("no session")
            return evaluate(expr, timeout)
        tab.js.side_effect = js
        return tab

    def test_a_check_that_fails_after_enter_is_tried_again(self):
        tab = self.failing_checks(1, {"messenger.history.v2": [history(MINE)]})
        self.assertEqual(run(messenger.send, tab, TEXT, chat_id="u2i-chat1")[0], "отправлено в чат u2i-chat1")

    def test_checks_that_all_fail_after_enter_say_enter_was_pressed(self):
        # an error here would read as 'not sent' and the message could be sent twice under the user's name
        tab = self.failing_checks(10, {})
        out, log, _ = run(messenger.send, tab, TEXT, chat_id="u2i-chat1")
        self.assertTrue(out.startswith("⚠️ Enter нажат, но в истории чата u2i-chat1 сообщения не видно."), out)
        self.assertEqual(log.warning.call_args_list[0], call("avito send: history check failed: %s", ANY))
        tab.close.assert_called_once()

    def test_chat_of_a_listing_not_found(self):
        tab = send_tab({"avito.getChats.v5": [ok({"channels": [{"channelId": "u2i-x", "lastMessage": THEIRS}]})] * 10},
                       hrefs=["https://www.avito.ru" + ITEM] * 10)
        out, log, _ = run(messenger.send, tab, TEXT, item_url="https://www.avito.ru" + ITEM)
        self.assertTrue(out.startswith("⚠️ Enter нажат, но в истории чата (не определён) сообщения не видно."), out)
        self.assertEqual(len(tab.sent), 10)
        log.warning.assert_called_once_with("avito send: message not seen in history, chat %s", None)

    def test_focus_left_on_a_dead_tab_does_not_hide_the_result(self):
        tab = send_tab({"messenger.history.v2": [history(MINE)]})
        typed = tab.call.side_effect

        def call_(method, **params):
            if params == {"enabled": False}:
                raise RuntimeError("Emulation.setFocusEmulationEnabled: target closed")
            return typed(method, **params)
        tab.call.side_effect = call_
        self.assertEqual(run(messenger.send, tab, TEXT, chat_id="u2i-chat1")[0], "отправлено в чат u2i-chat1")

    def test_nothing_to_send_or_nowhere(self):
        for text, kw, out in (("  \n ", {"chat_id": "u2i-chat1"}, "пустой текст — ничего не отправлено"),
                              (TEXT, {}, "нужно одно из двух: chat_id (из avito_chats) или item_url (ссылка на объявление)"),
                              (TEXT, {"chat_id": "", "item_url": None}, "нужно одно из двух: chat_id (из avito_chats) или item_url (ссылка на объявление)"),
                              (TEXT, {"chat_id": "u2i-chat1", "item_url": "https://www.avito.ru" + ITEM},
                               "нужно одно из двух: chat_id (из avito_chats) или item_url (ссылка на объявление)")):
            with self.subTest(text=text, kw=kw), patch.object(messenger, "tab_for") as tab_for:
                self.assertEqual(messenger.send(text, **kw), out)
                tab_for.assert_not_called()



class SmallPartsTests(unittest.TestCase):
    def test_chat_id_from_an_id_or_any_link(self):
        for chat in ("u2i-abc", " https://www.avito.ru/profile/messenger/channel/u2i-abc ", ".../channel/u2i-abc/",
                     ".../channel/u2i-abc?from=item", ".../channel/u2i-abc/?from=item"):
            with self.subTest(chat):
                self.assertEqual(messenger._channel_id(chat), "u2i-abc")

    def test_message_of_empty_chunks_names_its_type(self):
        msg = {"type": "location", "body": {"chunks": [{"type": "map"}, {"value": {}}]}}
        self.assertEqual(messenger._text(msg), "[location]")

if __name__ == "__main__":
    unittest.main()
