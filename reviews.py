"""Reviews on Ozon and AliExpress: what waits for a review, and leaving one.

Both sites take a review through the same JSON API their own review form uses, called from the
logged-in tab.  Text only: photos and videos are not uploaded.
Endpoints were read from the sites' form bundles on 2026-10-02:
- Ozon: rp-product-web-review-form-v2.js posts the form to composer action `submitReviewFormWeb`
  (the id comes with the form, see _ozon_form);
- AliExpress: RedCreateReview posts to /aer-jsonapi/review/v3/desktop/create by order line id.
"""
import json
import re

import ali
import ozon

OZON_TEXT_MAX = 3000        # textAreaCell.maxLength of the form
ALI_TEXT_MAX = 10000        # create-review-config text.limit
ALI_WAITING = "/aer-jsonapi/review/v1/desktop/waiting-reviews"


def _check(rating, text, limit):
    if int(rating) not in range(1, 6):
        raise ValueError("rating: от 1 до 5")
    text = (text or "").strip()
    if len(text) > limit:
        raise ValueError(f"текст длиннее {limit} символов ({len(text)})")
    return int(rating), text


# ------------------------------------------------------------------------------ Ozon
def ozon_waiting(limit=30):
    tab = ozon._tab()
    items, url = [], "/my/waiting-reviews"
    try:
        for _ in range(20):
            page = ozon._page(tab, url)
            for w in ozon._widgets(page, "webProductsForReview"):
                for it in w.get("items", []):
                    items.append((it.get("sku", ""), it.get("productName", {}).get("text", ""),
                                  it.get("aspectName", {}).get("text", "")))
            url = next((w.get("nextPage") for w in ozon._widgets(page, "paginator") if w.get("nextPage")), None)
            if len(items) >= limit or not url:
                break
    finally:
        tab.close()
    head = f"Ozon: ждут отзыва — {len(items[:limit])}" + (" (есть ещё)" if url or len(items) > limit else "")
    rows = [f"{sku}\t{title[:110]}\t{variant[:50]}" for sku, title, variant in items[:limit]]
    return head + "\nsku\tтовар\tвариант\n" + ("\n".join(rows) if rows else "(ничего)")


def _ozon_form(tab, sku):
    page = ozon._page(tab, f"/modal/create-new-review?item_ids={sku}")
    form = next(iter(ozon._widgets(page, "webReviewForm")), None)
    if not form:
        raise RuntimeError(f"Ozon не открыл форму отзыва на {sku}: товар не куплен или ссылка устарела")
    return form


def ozon_review(sku_or_url, rating, text, anonymous=False, accept_conditions=False):
    rating, text = _check(rating, text, OZON_TEXT_MAX)
    sku = ozon._sku(sku_or_url)
    tab = ozon._tab()
    try:
        form = _ozon_form(tab, sku)
        title = form.get("productCell", {}).get("productName", {}).get("text", str(sku))
        if form.get("reviewUuid"):
            return f"не отправлено: на «{title[:80]}» отзыв уже есть, редактировать этот инструмент не умеет"
        # the same checks the form makes before sending (getErrorType)
        if not text and form.get("deliveryType", "RECEIVED") != "RECEIVED":
            return f"не отправлено: «{title[:80]}» не получен, Ozon требует текст с объяснением"
        if not text and rating < (form.get("minRatingCountForNoExplanation") or 0):
            return f"не отправлено: при оценке {rating} Ozon требует текст с объяснением"
        action = form["footerCell"]["button"]["common"]["action"]
        data = {"opinion": {"content": {"score": rating, "photos": [], "videos": [], "comment": text},
                            "isAnonymous": bool(anonymous),
                            "product": {"itemId": form.get("productCell", {}).get("sku") or str(sku)}}}
        r = ozon._fetch(tab, "/api/composer-api.bx/_action/" + action["id"], "POST",
                        dict(data, **(action.get("params") or {})))
        dialog = r.get("promoConditionsDialog")
        if dialog and not r.get("opinionUuid"):
            # The item gives points for a review, and Ozon shows its conditions before sending.
            # The dialog's own «send» button carries the action that sends the review anyway.
            conditions = " · ".join(t for t in ozon._texts(dialog) if t.strip())
            if not accept_conditions:
                return (f"не отправлено: Ozon показал условия баллов за отзыв на «{title[:80]}»:\n{conditions}\n"
                        "Отправить всё равно — тот же вызов с accept_conditions=True")
            send = dialog["sendReviewButton"]["common"]["action"]
            r = ozon._fetch(tab, "/api/composer-api.bx/_action/" + send["id"], "POST",
                            dict(data, **(send.get("params") or {})))
    finally:
        tab.close()
    if not r.get("opinionUuid"):
        return f"Ozon не принял отзыв на «{title[:80]}»: {json.dumps(r, ensure_ascii=False)[:400]}"
    return (f"отзыв отправлен: {'★' * rating} «{title[:90]}»\n"
            f"https://www.ozon.ru/product/{sku}/reviews?ruuid={r['opinionUuid']}")


# ------------------------------------------------------------------------------ AliExpress
def _ali_first_page(tab):
    """The first page of the list comes only inside the server-rendered «Мои отзывы» page,
    as props of the RedWaitingForReview widget; the API serves the pages after it."""
    h = tab.js("fetch('https://feedback.aliexpress.ru/management/feedbackBuyerList.htm', "
               "{credentials: 'include'}).then(r => r.text())", timeout=60) or ""
    i = h.find("RedWaitingForReview")
    i = h.find('"products":', i) if i >= 0 else -1
    if i < 0:
        return [], None
    dec = json.JSONDecoder()
    products, end = dec.raw_decode(h, i + len('"products":'))
    m = re.compile(r'\s*,\s*"pagination":\s*').match(h, end)   # null when the list fits one page
    return products, dec.raw_decode(h, m.end())[0] if m else None


def ali_waiting(limit=30):
    tab = ali._tab()
    try:
        products, pagination = _ali_first_page(tab)
        while pagination and len(products) < limit:
            d = ali._fetch(tab, ALI_WAITING, {"pagination": dict(pagination, pageSize=20)}).get("data") or {}
            products += d.get("products") or []
            pagination = d.get("pagination") if d.get("products") else None
    finally:
        tab.close()
    head = f"AliExpress: ждут отзыва — {len(products[:limit])}" + (" (есть ещё)" if pagination or len(products) > limit else "")
    rows = [f"{p.get('orderLineId')}\t{p.get('id')}\t{p.get('title', '')[:110]}\t{p.get('skuProperties', '')[:50]}"
            for p in products[:limit]]
    return (head + "\nстрока заказа\tid товара\tтовар\tвариант\n" + ("\n".join(rows) if rows else "(ничего)"))


def ali_review(order_line_id, rating, text, anonymous=False):
    rating, text = _check(rating, text, ALI_TEXT_MAX)
    line = re.sub(r"\D", "", str(order_line_id))
    tab = ali._tab()
    try:
        # find the item of this order line: the config needs it and its title goes in the answer
        products, pagination = _ali_first_page(tab)
        while pagination and not any(p.get("orderLineId") == line for p in products):
            d = ali._fetch(tab, ALI_WAITING, {"pagination": dict(pagination, pageSize=20)}).get("data") or {}
            products += d.get("products") or []
            pagination = d.get("pagination") if d.get("products") else None
        p = next((p for p in products if p.get("orderLineId") == line), None)
        if not p:
            return f"не отправлено: строки заказа {line} нет среди ждущих отзыва (ali_reviews_waiting)"
        conf = ali._fetch(tab, "/aer-jsonapi/review/v1/desktop/create-review-config",
                          {"productId": p["id"], "productSourceId": p.get("sourceId", 0), "orderLineId": line})
        anon = (((conf.get("data") or {}).get("mainScreen") or {}).get("publishAnonymous") or {}).get("enabled")
        if anonymous and not anon:
            return "не отправлено: AliExpress не даёт опубликовать этот отзыв анонимно"
        r = ali._fetch(tab, "/aer-jsonapi/review/v3/desktop/create",
                       {"orderLineId": line, "images": [], "text": text, "grade": rating,
                        "anonymously": bool(anonymous)})
    finally:
        tab.close()
    d = r.get("data") or {}
    if not d:
        return f"AliExpress не принял отзыв на «{p['title'][:80]}»: {json.dumps(r, ensure_ascii=False)[:400]}"
    return (f"отзыв отправлен: {'★' * rating} «{p['title'][:90]}» — на модерации, публикуют в течение 48 часов\n"
            f"https://aliexpress.ru/item/{p['id']}.html")
