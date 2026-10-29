"""Reviews on Ozon and AliExpress: the lists of items waiting for a review, and what leaving one would send.
No requests to shops: every call that would post a review is a mock.  Run: .venv/bin/python -B -m unittest -v test_reviews"""
import json
import unittest
from unittest.mock import MagicMock, patch

import ali
import ozon
import reviews


def page(widgets=None, **top):
    """An Ozon composer page: its widget states are JSON strings."""
    return {"widgetStates": {k: json.dumps(v) for k, v in (widgets or {}).items()}, **top}


# ------------------------------------------------------------------------------ Ozon
LONG = "Набор прецизионных отвёрток " + "с битами и держателем " * 6
WAITING = {
    "/my/waiting-reviews": page({"webProductsForReview-1": {"items": [
        {"sku": 100001, "productName": {"text": "Кабель USB-C"}, "aspectName": {"text": "чёрный, 1 м"}},
        {"sku": 100002, "productName": {"text": "Зарядка 65 Вт"}}]},
        "paginator-2": {}, "paginator-3": {"nextPage": "/my/waiting-reviews?page=2"}}),
    "/my/waiting-reviews?page=2": page({"webProductsForReview-1": {"items": [
        {"sku": 100003, "productName": {"text": LONG}, "aspectName": {"text": "Комплектация: " + "кейс, " * 12}}]}}),
}
WAITING_ROWS = ["100001\tКабель USB-C\tчёрный, 1 м", "100002\tЗарядка 65 Вт\t",
                f"100003\t{LONG[:110]}\t{('Комплектация: ' + 'кейс, ' * 12)[:50]}"]


class OzonWaitingTests(unittest.TestCase):
    def waiting(self, pages=WAITING, **kw):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), \
                patch.object(ozon, "_page", side_effect=lambda t, url: pages[url]) as get:
            out = reviews.ozon_waiting(**kw)
        tab.close.assert_called_once_with()
        return out, [c.args[1] for c in get.call_args_list]

    def test_every_page(self):
        out, urls = self.waiting()
        self.assertEqual(out, "\n".join(["Ozon: ждут отзыва — 3", "sku\tтовар\tвариант"] + WAITING_ROWS))
        self.assertEqual(urls, ["/my/waiting-reviews", "/my/waiting-reviews?page=2"])
        self.assertEqual(self.waiting(limit=3)[0], out)          # exactly the limit and no more pages

    def test_limit_reached_with_more_pages(self):
        out, urls = self.waiting(limit=2)
        self.assertEqual(out, "\n".join(["Ozon: ждут отзыва — 2 (есть ещё)", "sku\tтовар\tвариант"] + WAITING_ROWS[:2]))
        self.assertEqual(urls, ["/my/waiting-reviews"])

    def test_limit_below_one_page(self):
        out, _ = self.waiting({"/my/waiting-reviews": WAITING["/my/waiting-reviews?page=2"]}, limit=0)
        self.assertEqual(out, "Ozon: ждут отзыва — 0 (есть ещё)\nsku\tтовар\tвариант\n(ничего)")

    def test_nothing_waits(self):
        out, _ = self.waiting({"/my/waiting-reviews": page()})
        self.assertEqual(out, "Ozon: ждут отзыва — 0\nsku\tтовар\tвариант\n(ничего)")


FORM_URL = "/modal/create-new-review?item_ids=100001"
FORM = {"productCell": {"productName": {"text": "Кабель USB-C"}, "sku": "100002"}, "deliveryType": "RECEIVED",
        "minRatingCountForNoExplanation": 4,
        "footerCell": {"button": {"common": {"action": {"id": "submitReviewFormWeb", "params": {"formId": "f-1"}}}}}}
SUBMIT = "/api/composer-api.bx/_action/submitReviewFormWeb"
DIALOG = {"title": "Баллы за отзыв", "items": [{"text": "до 200 баллов"}, {"text": " "}],
          "sendReviewButton": {"text": "Отправить", "common": {"action": {"id": "sendWithPromo", "params": {"promo": "p-1"}}}}}


def opinion(score, comment, anonymous=False, item="100002"):
    return {"opinion": {"content": {"score": score, "photos": [], "videos": [], "comment": comment},
                        "isAnonymous": anonymous, "product": {"itemId": item}}}


class OzonReviewTests(unittest.TestCase):
    def review(self, *args, form=FORM, answers=(), **kw):
        tab = MagicMock()
        pages = {FORM_URL: page({"webReviewForm-1": form})}
        with patch.object(ozon, "_tab", return_value=tab), \
                patch.object(ozon, "_page", side_effect=lambda t, url: pages[url]), \
                patch.object(ozon, "_fetch", side_effect=list(answers)) as post:
            out = reviews.ozon_review(*args, **kw)
        tab.close.assert_called_once_with()
        self.assertTrue(all(c.args[0] is tab for c in post.call_args_list))
        return out, [c.args[1:] for c in post.call_args_list]

    def test_sent(self):
        out, sent = self.review("100001", 5, "  Хороший кабель  ", answers=[{"opinionUuid": "u-1"}])
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(5, "Хороший кабель"), formId="f-1"))])
        self.assertEqual(out, "отзыв отправлен: ★★★★★ «Кабель USB-C»\nhttps://www.ozon.ru/product/100001/reviews?ruuid=u-1")

    def test_product_link_anonymous_and_no_sku_in_the_form(self):
        form = dict(FORM, productCell={"productName": {"text": "Кабель USB-C"}})
        form["footerCell"] = {"button": {"common": {"action": {"id": "submitReviewFormWeb"}}}}
        out, sent = self.review("https://www.ozon.ru/product/kabel-usb-c-100001/?at=x", "4", "ok", anonymous=1,
                                form=form, answers=[{"opinionUuid": "u-2"}])
        self.assertEqual(sent, [(SUBMIT, "POST", opinion(4, "ok", anonymous=True, item="100001"))])
        self.assertTrue(out.startswith("отзыв отправлен: ★★★★ «Кабель USB-C»\n"))

    def test_already_reviewed(self):
        out, sent = self.review("100001", 5, "ok", form=dict(FORM, reviewUuid="old"))
        self.assertEqual(out, "не отправлено: на «Кабель USB-C» отзыв уже есть, редактировать этот инструмент не умеет")
        self.assertEqual(sent, [])

    def test_not_received_needs_a_text(self):
        form = dict(FORM, deliveryType="NOT_RECEIVED")
        out, sent = self.review("100001", 5, "  ", form=form)
        self.assertEqual(out, "не отправлено: «Кабель USB-C» не получен, Ozon требует текст с объяснением")
        self.assertEqual(sent, [])
        out, sent = self.review("100001", 1, "не пришёл", form=form, answers=[{"opinionUuid": "u-3"}])
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(1, "не пришёл"), formId="f-1"))])

    def test_low_rating_needs_a_text(self):
        out, sent = self.review("100001", 3, "")
        self.assertEqual(out, "не отправлено: при оценке 3 Ozon требует текст с объяснением")
        self.assertEqual(sent, [])
        out, sent = self.review("100001", 4, None, answers=[{"opinionUuid": "u-4"}])
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(4, ""), formId="f-1"))])
        out, sent = self.review("100001", 1, "", form=dict(FORM, minRatingCountForNoExplanation=None),
                                answers=[{"opinionUuid": "u-5"}])
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(1, ""), formId="f-1"))])

    def test_points_conditions_stop_the_review(self):
        out, sent = self.review("100001", 5, "ok", answers=[{"promoConditionsDialog": DIALOG}])
        self.assertEqual(out, "не отправлено: Ozon показал условия баллов за отзыв на «Кабель USB-C»:\n"
                              "Баллы за отзыв · до 200 баллов · Отправить\n"
                              "Отправить всё равно — тот же вызов с accept_conditions=True")
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(5, "ok"), formId="f-1"))])

    def test_points_conditions_accepted(self):
        out, sent = self.review("100001", 5, "ok", accept_conditions=True,
                                answers=[{"promoConditionsDialog": DIALOG}, {"opinionUuid": "u-6"}])
        self.assertEqual(sent, [(SUBMIT, "POST", dict(opinion(5, "ok"), formId="f-1")),
                                ("/api/composer-api.bx/_action/sendWithPromo", "POST", dict(opinion(5, "ok"), promo="p-1"))])
        self.assertEqual(out, "отзыв отправлен: ★★★★★ «Кабель USB-C»\nhttps://www.ozon.ru/product/100001/reviews?ruuid=u-6")

    def test_conditions_with_a_saved_review_are_not_asked_about(self):
        out, sent = self.review("100001", 5, "ok", answers=[{"promoConditionsDialog": DIALOG, "opinionUuid": "u-7"}])
        self.assertEqual(len(sent), 1)
        self.assertTrue(out.startswith("отзыв отправлен: "))

    def test_not_accepted(self):
        out, _ = self.review("100001", 5, "ok", answers=[{"error": "слишком коротко"}])
        self.assertEqual(out, 'Ozon не принял отзыв на «Кабель USB-C»: {"error": "слишком коротко"}')

    def test_no_review_form(self):
        tab = MagicMock()
        with patch.object(ozon, "_tab", return_value=tab), patch.object(ozon, "_fetch") as post, \
                patch.object(ozon, "_page", return_value=page({"webProductHeading-1": {}})) as get:
            with self.assertRaisesRegex(RuntimeError, "^Ozon не открыл форму отзыва на 100001: товар не куплен или ссылка устарела$"):
                reviews.ozon_review("100001", 5, "ok")
        self.assertEqual(get.call_args.args, (tab, FORM_URL))
        tab.close.assert_called_once_with()
        post.assert_not_called()

    def test_bad_input_opens_no_tab(self):
        with patch.object(ozon, "_tab") as tab:
            for rating in (0, 6):
                with self.assertRaisesRegex(ValueError, "^rating: от 1 до 5$"):
                    reviews.ozon_review("100001", rating, "ok")
            with self.assertRaisesRegex(ValueError, r"^текст длиннее 3000 символов \(3001\)$"):
                reviews.ozon_review("100001", 5, "я" * 3001)
        tab.assert_not_called()
        self.assertEqual(self.review("100001", 5, " " + "я" * 3000 + " ", answers=[{"opinionUuid": "u"}])[1][0][2]
                         ["opinion"]["content"]["comment"], "я" * 3000)


# ------------------------------------------------------------------------------ AliExpress
P1 = {"orderLineId": "8100000000000001", "id": "1005000000000001", "sourceId": 7, "title": "Паяльник T12",
      "skuProperties": "EU"}
P2 = {"orderLineId": "8100000000000002", "id": "1005000000000002", "title": "Жало K"}
P3 = {"orderLineId": "8100000000000003", "id": "1005000000000003", "title": LONG, "skuProperties": "Цвет: " + "серый " * 10}
ROWS = ["8100000000000001\t1005000000000001\tПаяльник T12\tEU", "8100000000000002\t1005000000000002\tЖало K\t",
        f"8100000000000003\t1005000000000003\t{LONG[:110]}\t{P3['skuProperties'][:50]}"]
HEAD = "строка заказа\tid товара\tтовар\tвариант"


def ali_html(products, pagination):
    """«Мои отзывы»: the first page is in the RedWaitingForReview widget's props; another "products" before it."""
    props = json.dumps({"products": products, "pagination": pagination}, ensure_ascii=False, separators=(",", ":"))
    return ('<script>{"products": [{"title": "реклама"}]}</script>'
            f'<div data-widget="RedWaitingForReview"></div><script>window.__props = {props};</script>')


class AliSite:
    """The tab's HTML of «Мои отзывы» and ali._fetch answers by path; records every request."""
    def __init__(self, html, pages=(), config=None, created=None):
        self.html, self.pages, self.config, self.created = html, list(pages), config, created
        self.sent = []

    def fetch(self, tab, path, body):
        self.sent.append((path, body))
        if path == reviews.ALI_WAITING:
            return self.pages.pop(0)
        return {"/aer-jsonapi/review/v1/desktop/create-review-config": self.config,
                "/aer-jsonapi/review/v3/desktop/create": self.created}[path]

    def run(self, f, *args, **kw):
        tab = MagicMock()
        tab.js.return_value = self.html
        with patch.object(ali, "_tab", return_value=tab), patch.object(ali, "_fetch", side_effect=self.fetch):
            out = f(*args, **kw)
        tab.close.assert_called_once_with()
        tab.js.assert_called_once_with("fetch('https://feedback.aliexpress.ru/management/feedbackBuyerList.htm', "
                                       "{credentials: 'include'}).then(r => r.text())", timeout=60)
        return out


TWO_PAGES = dict(html=ali_html([P1, P2], {"page": 2, "lastId": "x"}),
                 pages=[{"data": {"products": [P3], "pagination": {"page": 3, "lastId": "y"}}},
                        {"data": {"products": [], "pagination": {"page": 4}}}])


class AliWaitingTests(unittest.TestCase):
    def test_every_page(self):
        site = AliSite(**TWO_PAGES)
        out = site.run(reviews.ali_waiting)
        self.assertEqual(out, "\n".join(["AliExpress: ждут отзыва — 3", HEAD] + ROWS))
        self.assertEqual(site.sent, [(reviews.ALI_WAITING, {"pagination": {"page": 2, "lastId": "x", "pageSize": 20}}),
                                     (reviews.ALI_WAITING, {"pagination": {"page": 3, "lastId": "y", "pageSize": 20}})])

    def test_limit(self):
        site = AliSite(**TWO_PAGES)
        self.assertEqual(site.run(reviews.ali_waiting, limit=2), "\n".join(["AliExpress: ждут отзыва — 2 (есть ещё)", HEAD] + ROWS[:2]))
        self.assertEqual(site.sent, [])
        site = AliSite(ali_html([P1, P2], None))
        self.assertEqual(site.run(reviews.ali_waiting, limit=1), "\n".join(["AliExpress: ждут отзыва — 1 (есть ещё)", HEAD, ROWS[0]]))

    def test_one_page(self):
        self.assertEqual(AliSite(ali_html([P2], None)).run(reviews.ali_waiting), "\n".join(["AliExpress: ждут отзыва — 1", HEAD, ROWS[1]]))
        self.assertEqual(AliSite(ali_html([P1, P2], None)).run(reviews.ali_waiting, limit=2),
                         "\n".join(["AliExpress: ждут отзыва — 2", HEAD] + ROWS[:2]))

    def test_no_list_on_the_page(self):
        for html in (None, "<html>войдите</html>", '<div data-widget="RedWaitingForReview"></div>'):
            self.assertEqual(AliSite(html).run(reviews.ali_waiting), f"AliExpress: ждут отзыва — 0\n{HEAD}\n(ничего)")

    def test_empty_answer_ends_the_list(self):
        site = AliSite(ali_html([P1], {"page": 2}), pages=[{"data": None}])
        self.assertEqual(site.run(reviews.ali_waiting), "\n".join(["AliExpress: ждут отзыва — 1", HEAD, ROWS[0]]))


CONFIG = "/aer-jsonapi/review/v1/desktop/create-review-config"
CREATE = "/aer-jsonapi/review/v3/desktop/create"


def config(anonymous):
    return {"data": {"mainScreen": {"publishAnonymous": {"enabled": anonymous}}}}


class AliReviewTests(unittest.TestCase):
    def test_sent(self):
        site = AliSite(**TWO_PAGES, config=config(False), created={"data": {"id": "r-1"}})
        out = site.run(reviews.ali_review, "8100000000000002", 4, "  Отличное жало  ")
        self.assertEqual(site.sent, [
            (CONFIG, {"productId": "1005000000000002", "productSourceId": 0, "orderLineId": "8100000000000002"}),
            (CREATE, {"orderLineId": "8100000000000002", "images": [], "text": "Отличное жало", "grade": 4, "anonymously": False})])
        self.assertEqual(out, "отзыв отправлен: ★★★★ «Жало K» — на модерации, публикуют в течение 48 часов\n"
                              "https://aliexpress.ru/item/1005000000000002.html")

    def test_line_on_a_later_page_and_anonymous(self):
        site = AliSite(**TWO_PAGES, config=config(True), created={"data": {"id": "r-2"}})
        out = site.run(reviews.ali_review, "№ 8100-0000-0000-0003", "5", "ok", anonymous=True)
        self.assertEqual(site.sent, [
            (reviews.ALI_WAITING, {"pagination": {"page": 2, "lastId": "x", "pageSize": 20}}),
            (CONFIG, {"productId": "1005000000000003", "productSourceId": 0, "orderLineId": "8100000000000003"}),
            (CREATE, {"orderLineId": "8100000000000003", "images": [], "text": "ok", "grade": 5, "anonymously": True})])
        self.assertEqual(out, f"отзыв отправлен: ★★★★★ «{LONG[:90]}» — на модерации, публикуют в течение 48 часов\n"
                              "https://aliexpress.ru/item/1005000000000003.html")

    def test_source_id_goes_to_the_config(self):
        site = AliSite(**TWO_PAGES, config={}, created={"data": {"id": "r-3"}})
        site.run(reviews.ali_review, 8100000000000001, 1, "")
        self.assertEqual(site.sent[0], (CONFIG, {"productId": "1005000000000001", "productSourceId": 7,
                                                 "orderLineId": "8100000000000001"}))

    def test_line_not_waiting(self):
        site = AliSite(**TWO_PAGES)
        out = site.run(reviews.ali_review, "8199999999999999", 5, "ok")
        self.assertEqual(out, "не отправлено: строки заказа 8199999999999999 нет среди ждущих отзыва (ali_reviews_waiting)")
        self.assertEqual([path for path, _ in site.sent], [reviews.ALI_WAITING, reviews.ALI_WAITING])

    def test_anonymous_not_allowed(self):
        site = AliSite(**TWO_PAGES, config=config(False))
        out = site.run(reviews.ali_review, "8100000000000001", 5, "ok", anonymous=True)
        self.assertEqual(out, "не отправлено: AliExpress не даёт опубликовать этот отзыв анонимно")
        self.assertEqual([path for path, _ in site.sent], [CONFIG])

    def test_not_accepted(self):
        site = AliSite(**TWO_PAGES, config=config(True), created={"data": None, "error": "текст"})
        out = site.run(reviews.ali_review, "8100000000000001", 5, "ok")
        self.assertEqual(out, 'AliExpress не принял отзыв на «Паяльник T12»: {"data": null, "error": "текст"}')

    def test_bad_input_opens_no_tab(self):
        with patch.object(ali, "_tab") as tab:
            with self.assertRaisesRegex(ValueError, "^rating: от 1 до 5$"):
                reviews.ali_review("8100000000000001", 6, "ok")
            with self.assertRaisesRegex(ValueError, r"^текст длиннее 10000 символов \(10001\)$"):
                reviews.ali_review("8100000000000001", 5, "я" * 10001)
        tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
