"""Biggeek (biggeek.ru): search, product card. Read only. The site has no product reviews (only «Вопросы и ответы»).

Search is the site's Diginetica widget (digi.py, shared with PiterGSM). The card is server-rendered: its variants,
prices and specs are in <script id="product-properties-json">, the rest in JSON-LD and named nodes, read after goto.
The card shows no delivery or pickup terms. Prices are the same for every city.
"""
import html
import re

import digi
from cdp import tab_for
from shoplog import log

SHOP = {"site": "biggeek", "domain": "biggeek.ru", "home": "https://biggeek.ru", "name": "Biggeek"}
HOME = SHOP["home"]
NO_SLUG = "нужна ссылка на товар Biggeek (biggeek.ru/products/…) из biggeek_search"
NONE = ("На Biggeek нет отзывов покупателей о товарах: на карточке только «Вопросы и ответы». "
        "Отзывы о модели — на маркетплейсах (ozon_reviews, wb_reviews, ym_reviews).")
KEY_SPECS = 20
STOCK = {"InStock": "есть", "OutOfStock": "нет в наличии", "PreOrder": "предзаказ"}   # schema.org availability
# named nodes only: the page's inline scripts also hold session data
CARD_JS = r"""(() => { const j = document.getElementById('product-properties-json'); if (!j) return null;
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => { try { return JSON.parse(s.textContent) } catch (e) { return null } }).find(x => x && x['@type'] === 'Product');
  const review = [...document.querySelectorAll('.tabs-content__toggle')].find(t => t.textContent.trim() === 'Обзор');
  return {path: location.pathname, props: JSON.parse(j.textContent), ld: ld || {},
    h1: document.querySelector('h1')?.textContent.trim() || '', subtitle: document.querySelector('.produt-section__subtitle')?.textContent.trim() || '',
    photos: [...new Set([...document.querySelectorAll('.sl-prewiew [data-img]')].map(e => e.dataset.img))],
    overview: review ? [...review.nextElementSibling.querySelectorAll('h3, p, li')].map(e => e.textContent.trim()).join('\n') : ''} })()"""


def search(query, price_min=None, price_max=None, sort="relevance", page=1, limit=digi.PAGE):
    return digi.search(SHOP, query, price_min, price_max, sort, page, limit)


def reviews(id_or_url, sort="useful", with_media=False, page=1, limit=20):
    return NONE


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _slug(url_or_id):
    s = str(url_or_id).strip()
    m = re.match(r"(?:https?://)?(?:www\.)?(?:biggeek\.ru)?/products/([\w-]+)", s)
    return m.group(1) if m else None


def item(url_or_id, full=False):
    slug = _slug(url_or_id)
    if not slug:
        return NO_SLUG
    url = f"{HOME}/products/{slug}"
    tab = tab_for("biggeek.ru")
    try:
        tab.goto(url, "biggeek", wait_js="document.getElementById('product-properties-json')")
        p = tab.js(CARD_JS)
    finally:
        tab.close()
    if not p or p.get("path") != f"/products/{slug}":          # the tab may still hold the previous card
        log.warning("biggeek item %s: no product card", url)
        return f"⚠️ Biggeek не показал карточку {url}: нет такого товара или проверка на бота (shop-chrome show, открыть сайт, повторить)."
    return _card(p, url, full)


def _card(p, url, full):
    props, ld = p["props"], p["ld"]
    pick = props.get("variantCharacteristicPicker") or {}
    offer = ld.get("offers") or {}
    lines = [p.get("h1") or ld.get("name", ""), url, _code(props, pick), _price(pick, offer), "наличие: " + _stock(offer),
             "получение: доставку и самовывоз карточка не показывает"]
    lines += [f"примечание: {p['subtitle']}"] if p.get("subtitle") else []
    lines += _variants(pick) + _specs(props, pick, full)
    lines += [f"комплектация: {', '.join(props['equipment'])}"] if props.get("equipment") else []
    photos = _photos(p.get("photos"), ld.get("image"))
    lines += ["фото (shop_images): " + " ".join(photos[:10])] if photos else []
    text = _text(p.get("overview") or ld.get("description"))
    return "\n".join(lines + ["отзывы: на Biggeek их нет (biggeek_reviews)", "\n" + (text if full else text[:2500])])


def _photos(gallery, ld_image):
    """The gallery's pictures (protocol-relative), else JSON-LD's one picture."""
    photos = [("https:" + u if u.startswith("//") else u) for u in gallery or []]
    return photos or ([ld_image] if ld_image else [])


def _code(props, pick):
    variant = pick.get("selectedVariantId")
    return f"артикул: {props.get('productId')}" + (f", вариант {variant}" if variant else "")


def _price(pick, offer):
    now = pick.get("price") or offer.get("price")
    old = pick.get("comparePrice")
    return f"цена: {now} ₽" + (f" (было {old}, −{round(100 - 100 * now / old)}%)" if now and old and old > now else "")


def _stock(offer):
    kind = (offer.get("availability") or "").rsplit("/", 1)[-1]
    return STOCK.get(kind, kind or "—")


def _variants(pick):
    """e.g. 'SIM-карта: eSIM — 104990 ₽ (этот); nano-SIM и eSIM — 109990 ₽'. Colors and memory sizes are separate products."""
    return [f"{c.get('name')}: " + "; ".join(_value(v) for v in c.get("values") or []) for c in pick.get("characteristics") or []]


def _value(v):
    return f"{v.get('label')} — {v.get('price')} ₽" + ("" if v.get("isAvailable") else ", нет в наличии") + (" (этот)" if v.get("isSelected") else "")


def _specs(props, pick, full):
    """The card's spec groups and this variant's own (a group with no items comes as [] from the site), first KEY_SPECS unless full."""
    own = (props.get("variantsFeatureGroups") or {}).get(str(pick.get("selectedVariantId"))) or {}
    groups = list((props.get("featureGroups") or {}).values()) + list(own.values())
    specs = [f"{x.get('name')}: {x.get('value')}" for g in groups for x in g if x.get("name") != "Артикул"]
    if not specs:
        return []
    more = len(specs) - KEY_SPECS
    return ["характеристики: " + "; ".join(specs if full else specs[:KEY_SPECS]) + (f" … ещё {more} (full=True)" if more > 0 and not full else "")]
