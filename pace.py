"""One request budget per shop site, shared by every process that drives the shop Chrome or calls a site's API.

Why: one browser and one IP serve the Desktop server, other sessions, agents, watch.py and ad-hoc scripts. Each
used to pace only itself, so together they made bursts the sites answer with bot checks and IP bans (Перекрёсток
banned the IP on 2026-11-08 after a bundle scan, two cart cycles and retries into the block). Here every request
takes a slot from one ledger (cache/pace.sqlite): spaced by the site's gap, within its caps per 1/10/60 min, and
none at all while the site has a block on record. A refusal says why, until when and what to do instead.

What this is not: it never makes requests look less automated. No user-agent or fingerprint changes, no proxies
or IP rotation, no captcha solving, no clearing of a ban by a program. It only sends fewer requests, spaced out,
and stops everyone at the first sign that a site wants us to stop. Keep it that way.

The numbers below are cautious guesses from the incidents named next to them, not measurements: every block
records how many requests the site had in the last 1/10/60 min (blocks.n1/n10/n60) — set the caps from those.
"""
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# `python -m unittest` (and coverage's and mutator's runs of it) drives fakes, not the shops: there nothing is paced or
# recorded and the real ledger is never opened. test_pace turns pacing back on with its own database and clock.
OFF = sys.argv[0].endswith("-m unittest")      # what unittest's own __main__ sets it to
DB = Path(tempfile.gettempdir()) / "shop-pace-test.sqlite" if OFF else Path(__file__).parent / "cache" / "pace.sqlite"
MAX_WAIT = 20.0      # s a call may sleep for its slot; longer and it is refused (a tool call must answer in time)
_now, _sleep = time.time, time.sleep


@dataclass(frozen=True)
class Policy:
    gap: dict        # kind ("page" load or "api" request) -> s after the site's previous request of any kind
    caps: tuple      # ((window s, most requests), ...) over both kinds
    cool: dict       # block kind -> s every request to the site stops; doubled for each block of the last 24 h


DEFAULT = Policy(gap={"page": 4.0, "api": 1.5}, caps=((60, 30), (600, 150), (3600, 600)),
                 cool={"check": 900, "throttle": 600, "ban": 3 * 3600})
# ServicePipe (X5): ~30 calls in a few seconds brought its check (2026-10-13); an IP ban after a bundle scan, two cart
# cycles and five retries into the block (2026-11-08)
SERVICEPIPE = Policy(gap={"page": 8.0, "api": 2.0}, caps=((60, 15), (600, 60), (3600, 200)),
                     cool={"check": 1800, "throttle": 1800, "ban": 6 * 3600})
# a site not yet learned: its bot check unknown, so half of DEFAULT until a block or a quiet month says otherwise
NEW = Policy(gap={"page": 6.0, "api": 2.0}, caps=((60, 12), (600, 50), (3600, 200)), cool=SERVICEPIPE.cool)
POLICY = {
    "ozon": DEFAULT, "wb": DEFAULT, "lamoda": DEFAULT, "goldapple": DEFAULT, "lenta": DEFAULT, "lavka": DEFAULT,
    "ali": DEFAULT,                  # its slider after a burst of review requests (2026-10-22)
    "ym": Policy(gap={"page": 5.0, "api": 2.0}, caps=((60, 12), (600, 60), (3600, 240)), cool=DEFAULT.cool),   # captcha
    "avito": Policy(gap={"page": 6.0, "api": 3.0}, caps=((60, 16), (600, 40), (3600, 120)),   # 439 on bursts, a CGNAT IP;
                    cool={"check": 1800, "throttle": 1800, "ban": 6 * 3600}),              # a search + its 15 look-ups = 16
    "vkusvill": Policy(gap=DEFAULT.gap, caps=((60, 30), (600, 150), (3600, 600)), cool=DEFAULT.cool),         # its API: 429 at 60/min
    "perekrestok": SERVICEPIPE, "5ka": SERVICEPIPE,
    "samokat": Policy(gap={"page": 20.0, "api": 2.0}, caps=((60, 15), (600, 60), (3600, 200)),               # its check after
                      cool=SERVICEPIPE.cool),                                                              # a handful of loads
    "eldorado": NEW, "mvideo": NEW, "dns": NEW, "citilink": NEW,                                   # added 2026-11-12
}
NAMES = {"ozon": "Ozon", "wb": "Wildberries", "ym": "Яндекс Маркет", "ali": "AliExpress", "avito": "Авито", "lamoda": "Lamoda",
         "goldapple": "Золотое яблоко", "lenta": "Лента", "samokat": "Самокат", "lavka": "Яндекс Лавка", "perekrestok": "Перекрёсток",
         "5ka": "Пятёрочка", "vkusvill": "ВкусВилл", "eldorado": "Эльдорадо", "mvideo": "М.Видео", "dns": "DNS",
         "citilink": "Ситилинк"}
KINDS = {"check": "проверка на бота", "throttle": "сайт ограничил частоту", "ban": "блокировка по IP"}
ADVICE = {"check": "Её может пройти человек: попроси пользователя пройти её во вкладке сайта (shop-chrome show), потом выполни "
                   "~/shop-mcp/shop-pace clear {site}.",
          "throttle": "Это не проверка, сайт просит реже: подожди или займись другими магазинами.",
          "ban": "Её не пройти, можно только ждать: займись другими магазинами, пользователю делать ничего не нужно."}
# what a block page shows: (where, text, block kind, what it is); text and title only on a short page — a block page is short
SIGNS = (("url", "/xpvnsulc/", "check", "проверка ServicePipe"),
         ("url", "showcaptcha", "check", "капча Яндекса"),
         ("slider", True, "check", "слайдер AliExpress"),
         ("text", "Проблемы со связью", "ban", "«Проблемы со связью» (ServicePipe)"),
         ("title", "Доступ ограничен", "throttle", "«Доступ ограничен» (Авито)"),
         ("text", "Доступ ограничен", "throttle", "«Доступ ограничен» (Авито)"))
SHORT = 3000


class Refused(RuntimeError):
    """A request the budget does not allow now; the message is the explanation for whoever asked."""


def policy(site):
    return POLICY.get(site, DEFAULT)


def acquire(site, kind="api", cost=1):
    """Take the site's next slot and sleep until it comes, or raise Refused (a block on record, or no slot soon)."""
    if OFF:
        return
    wait = _reserve(site, kind, cost)
    if wait > 0:
        _sleep(wait)


def _db():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB, timeout=30, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS events (site TEXT, t REAL, kind TEXT, cost INTEGER)")
    db.execute("CREATE INDEX IF NOT EXISTS events_site_t ON events (site, t)")
    db.execute("CREATE TABLE IF NOT EXISTS blocks (site TEXT, kind TEXT, detail TEXT, seen REAL, until REAL, n1 INTEGER, n10 INTEGER, n60 INTEGER)")
    return db


def _reserve(site, kind, cost):
    """The wait for the site's slot, written to the ledger before anyone sleeps: two callers at once get two slots."""
    now, pol = _now(), policy(site)
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM events WHERE t < ?", (now - 3600 - MAX_WAIT,))
        block = _active(db, site, now)
        if block:
            db.execute("ROLLBACK")
            raise _refusal(site, block, now)
        too_big = next(((w, most) for w, most in pol.caps if cost > most), None)
        if too_big:
            db.execute("ROLLBACK")
            raise Refused(f"⏸ {_name(site)}: {cost} запросов за раз больше предела {too_big[1]} за {_window(too_big[0])}. "
                          "Уменьши пакет (у avito_search — shipping) и не повторяй его таким.")
        rows = db.execute("SELECT t, cost FROM events WHERE site = ? AND t > ? ORDER BY t",
                          (site, now - max(w for w, _ in pol.caps))).fetchall()
        t, cap = _slot(rows, pol, kind, cost, now)
        if t - now > MAX_WAIT:
            db.execute("ROLLBACK")
            raise Refused(_budget_text(site, cap, t, now))
        db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (site, t, kind, cost))
        db.execute("COMMIT")
        return round(t - now, 3)
    finally:
        db.close()


def _slot(rows, pol, kind, cost, now):
    """(the earliest time the request fits, the cap that set it or None): the gap after the site's last slot, and
    room for cost in every window."""
    t, cap = (max(now, rows[-1][0] + pol.gap[kind]) if rows else now), None
    for window, most in pol.caps:
        used = 0
        for rt, rc in reversed(rows):
            used += rc
            if used > most - cost and rt + window > t:
                t, cap = rt + window, (window, most)
                break
    return t, cap


def _budget_text(site, cap, t, now):
    why = f"предел запросов — {cap[1]} за {_window(cap[0])}" if cap else "к сайту уже стоит очередь запросов других вызовов"
    return (f"⏸ {_name(site)}: {why}. Следующий не раньше {time.strftime('%H:%M:%S', time.localtime(t))} "
            f"(через {_span(t - now)}). Не повторяй раньше: займись другим магазином или подожди. Пределы общие для MCP, "
            "агентов и скриптов и берегут IP пользователя от бана; состояние — shop_limits.")


def blocked(site, kind, detail):
    """Record that the site showed a block of kind (check / throttle / ban): every request to it stops for the kind's
    time, twice that for each block of the last 24 h. The Refused to raise, with the explanation."""
    if OFF:
        return Refused(f"⏸ {_name(site)}: {KINDS[kind]} — {detail}")
    now, pol = _now(), policy(site)
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        recent = db.execute("SELECT COUNT(*) FROM blocks WHERE site = ? AND seen > ?", (site, now - 86400)).fetchone()[0]
        until = now + min(pol.cool[kind] * 2 ** recent, 86400)
        counts = [_count_in(db, site, w, now) for w in (60, 600, 3600)]
        db.execute("DELETE FROM blocks WHERE seen < ?", (now - 7 * 86400,))
        db.execute("INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (site, kind, detail, now, until, *counts))
        db.execute("COMMIT")
        return _refusal(site, _active(db, site, now), now)
    finally:
        db.close()


def _active(db, site, now):
    r = db.execute("SELECT kind, detail, seen, until, n1, n10, n60 FROM blocks WHERE site = ? AND until > ? ORDER BY until DESC LIMIT 1",
                   (site, now)).fetchone()
    return dict(zip(("kind", "detail", "seen", "until", "n1", "n10", "n60"), r)) if r else None


def _refusal(site, b, now):
    return Refused(f"⏸ {_name(site)}: {KINDS[b['kind']]} — {b['detail']}, с {_hm(b['seen'])}. Запросы к сайту остановлены до "
                   f"{_hm(b['until'])} (ещё {_span(b['until'] - now)}) для всех: MCP, агентов и скриптов. Не повторяй до этого "
                   f"времени. {ADVICE[b['kind']].format(site=site)}")


def clear(site, ban=False):
    """Lift the site's stop when the user passed its check; a ban only with ban=True — the user's own decision."""
    db = _db()
    try:
        b = _active(db, site, _now())
        if not b:
            return f"{_name(site)}: остановки нет"
        if b["kind"] == "ban" and not ban:
            return (f"{_name(site)}: это блокировка по IP, её снимает только время (до {_hm(b['until'])}). Снять раньше может "
                    f"только пользователь сам: ~/shop-mcp/shop-pace clear --ban {site}")
        db.execute("UPDATE blocks SET until = ? WHERE site = ? AND until > ?", (_now(), site, _now()))
        return f"{_name(site)}: остановка снята"
    finally:
        db.close()


def check_page(site, probe):
    """After a page load: if the page is a block page, record the block and raise its Refused. probe: {url, title,
    text (the start of the body's text), size (the body text's length), slider}, None when the page could not be read."""
    for where, sign, kind, what in SIGNS if probe and not OFF else ():
        if _shows(probe, where, sign):
            raise blocked(site, kind, what)


def _shows(probe, where, sign):
    """Whether the page shows sign in where: its url, its slider, or — on a short page only — its title or text."""
    if where == "slider":
        return bool(probe.get("slider"))
    if where != "url" and probe.get("size", SHORT) >= SHORT:
        return False
    return sign in (probe.get(where) or "")


def status():
    now, db = _now(), _db()
    try:
        lines = ["запросы к магазинам за 1 / 10 / 60 мин и их пределы (общие для всех процессов); ⏸ — остановлены"]
        for site in POLICY:
            b = _active(db, site, now)
            counts = "\t".join(f"{_count_in(db, site, w, now)}/{most}" for w, most in POLICY[site].caps)
            stop = f"⏸ {KINDS[b['kind']]} до {_hm(b['until'])} (ещё {_span(b['until'] - now)}): {b['detail']}" if b else ""
            lines.append(f"{_name(site)}\t{counts}\t{stop}")
        return "\n".join(lines)
    finally:
        db.close()


def _count_in(db, site, window, now):
    return db.execute("SELECT COALESCE(SUM(cost), 0) FROM events WHERE site = ? AND t > ? AND t <= ?",
                      (site, now - window, now)).fetchone()[0]


def _block(site):
    db = _db()
    try:
        return _active(db, site, _now())
    finally:
        db.close()


def _name(site):
    return NAMES.get(site, site)


def _hm(t):
    return time.strftime("%H:%M", time.localtime(t))


def _window(s):
    return f"{s // 60} мин"


def _span(s):
    s = max(0, round(s))
    if s < 60:
        return f"{s} с"
    h, m = divmod(s // 60, 60)
    return f"{h} ч {m} мин" if h else f"{m} мин"


USAGE = ("shop-pace status | wait <сайт> [page|api] | clear [--ban] <сайт>\n"
         "  status — запросы к магазинам и остановки; wait — взять слот перед своим запросом к сайту (ждёт до 20 с\n"
         "  или отказывает с причиной); clear — снять остановку после проверки, которую прошёл пользователь;\n"
         "  --ban — снять и блокировку по IP: только сам пользователь. Сайты: " + ", ".join(POLICY))


def _status_cmd(rest):
    if rest:
        return None
    print(status())
    return 0


def _wait_cmd(rest):
    if not rest or rest[0] not in POLICY or rest[1:] not in ([], ["page"], ["api"]):
        return None
    try:
        acquire(*rest)
    except Refused as e:
        print(e)
        return 1
    print("ok")
    return 0


def _clear_cmd(rest):
    sites = [a for a in rest if a != "--ban"]
    if len(sites) != 1 or sites[0] not in POLICY:
        return None
    print(clear(sites[0], ban="--ban" in rest))
    return 0 if _block(sites[0]) is None else 1


COMMANDS = {"status": _status_cmd, "wait": _wait_cmd, "clear": _clear_cmd}


def main(argv):
    """The shop-pace command; its exit code: 0 done, 1 refused, 2 wrong use (an unknown command, site or kind)."""
    cmd, rest = (argv[0], argv[1:]) if argv else ("status", [])
    code = COMMANDS[cmd](rest) if cmd in COMMANDS else None
    if code is None:
        print(USAGE)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
