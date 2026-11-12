"""PiterGSM (pitergsm.ru, Санкт-Петербург): search, product card. Read only. The site has no product reviews.

Search is the site's Diginetica widget (digi.py, shared with Biggeek). The card is a Bitrix page: JSON-LD Product
(sku, price, stock, photos) and named nodes (variants, stock and delivery lines, specs, «О товаре»), read after goto.
Variant tags carry only their labels: another color is another card. Delivery terms are the shop's own (СПб).
"""
import html
import re

import digi
from cdp import tab_for
from shoplog import log

SHOP = {"site": "pitergsm", "domain": "pitergsm.ru", "home": "https://pitergsm.ru", "name": "PiterGSM"}
HOME = SHOP["home"]
NO_LINK = "нужна ссылка на товар PiterGSM (pitergsm.ru/catalog/…/<id>/) из pitergsm_search"
NONE = ("На PiterGSM нет отзывов покупателей о товарах: на сайте только ссылка на отзывы о магазине на Яндекс Картах. "
        "Отзывы о модели — на маркетплейсах (ozon_reviews, wb_reviews, ym_reviews).")
KEY_SPECS = 20
# named nodes only: the page's inline scripts also hold the visitor's address and session
CARD_JS = r"""(() => { const h1 = document.querySelector('h1[data-product-name]'); if (!h1) return null;
  const t = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : null, all = s => [...document.querySelectorAll(s)];
  const ld = all('script[type="application/ld+json"]').map(s => { try { return JSON.parse(s.textContent) } catch (e) { return null } })
    .find(x => x && x['@type'] === 'Product');
  return {path: location.pathname, name: h1.dataset.productName, ld: ld || {},
    price: t(document.getElementById('sticky-price')), old: t(document.querySelector('.product__sticky [class*="price-old"], .product__sticky [class*="old-price"]')),
    avail: t(document.querySelector('.product-avail__link')),
    delivery: [...new Set(all('.prodinfolist__item, #tab-delivery .ul-special li').map(t).filter(s => /Доставка|Самовывоз|пригород/.test(s)))],
    variants: all('.product__options-row').map(r => ({name: t(r.querySelector('.product__options-label')),
      values: [...r.querySelectorAll('.tags__tag')].map(a => ({label: t(a), active: a.classList.contains('m-active')}))})),
    specs: all('.specs__item').map(i => ({name: t(i.querySelector('.specs__name')), val: t(i.querySelector('.specs__val'))})),
    about: all('#tab-about h3, #tab-about p, #tab-about li').map(t).join('\n')} })()"""


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=digi.PAGE):
    return digi.search(SHOP, query, price_min, price_max, sort, page, limit)


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    return NONE


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _path(url_or_id):
    """/catalog/<sections>/<id>/ of a card's link (the id alone does not make an address)."""
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?(?:pitergsm\.ru)?(/catalog/(?:[\w-]+/)+?\d+)/?(?:[?#].*)?", str(url_or_id).strip())
    return m.group(1) + "/" if m else None


def _rub(s):
    """21990 from ' 21 990 ₽ ', None when there is no number."""
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else None


def item(url_or_id, full=False):
    path = _path(url_or_id)
    if not path:
        return NO_LINK
    url = HOME + path
    tab = tab_for("pitergsm.ru")
    try:
        tab.goto(url, "pitergsm", wait_js="document.querySelector('h1[data-product-name]')")
        p = tab.js(CARD_JS)
    finally:
        tab.close()
    if not p or p.get("path") != path:          # the tab may still hold the previous card
        log.warning("pitergsm item %s: no product card", url)
        return f"⚠️ PiterGSM не показал карточку {url}: нет такого товара или проверка на бота (shop-chrome show, открыть сайт, повторить)."
    return _card(p, url, full)


def _card(p, url, full):
    ld = p["ld"]
    lines = _head(p, ld, url)
    lines += ["получение: " + "; ".join(p["delivery"])] if p.get("delivery") else []
    lines += [_variants(v) for v in p.get("variants") or []] + _specs(p.get("specs"), full) + _photos(ld.get("image"))
    text = _text(p.get("about"))
    return "\n".join(lines + ["отзывы: на PiterGSM их нет (pitergsm_reviews)", "\n" + (text if full else text[:2500])])


def _head(p, ld, url):
    offer = ld.get("offers") or {}
    now = offer.get("price") or _rub(p.get("price"))
    stock = p.get("avail") or "—"
    return [p.get("name", ""), url, f"артикул: {_id(url)}", _price(now, _rub(p.get("old"))), f"наличие: {stock}"]


def _specs(specs, full):
    """The «Характеристики» tab, first KEY_SPECS unless full; the site repeats some rows."""
    specs = list(dict.fromkeys(f"{_text(s.get('name'))}: {_text(s.get('val'))}" for s in specs or []))
    if not specs:
        return []
    more = len(specs) - KEY_SPECS
    return ["характеристики: " + "; ".join(specs if full else specs[:KEY_SPECS]) + (f" … ещё {more} (full=True)" if more > 0 and not full else "")]


def _photos(image):
    """JSON-LD gives a list of the card's pictures (or one as a string)."""
    photos = [image] if isinstance(image, str) else image or []
    return ["фото (shop_images): " + " ".join(photos[:10])] if photos else []


def _id(url):
    return url.rstrip("/").split("/")[-1]


def _price(now, old):
    return f"цена: {now or '—'} ₽" + (f" (было {old}, −{round(100 - 100 * now / old)}%)" if now and old and old > now else "")


def _variants(group):
    """e.g. 'Цвет: Белый (этот); Чёрный' — the site gives no price or link of the other variants."""
    return f"{_text(group.get('name'))}: " + "; ".join(v.get("label", "") + (" (этот)" if v.get("active") else "") for v in group.get("values") or [])
