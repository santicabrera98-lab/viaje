"""Utilidades compartidas por todas las fuentes."""
import asyncio
import base64
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "viaje.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
CACHE_PATH = DATA_DIR / "cache.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_eur(text):
    """'24,40 €' / '€18.12' / '55 €' -> float."""
    if text is None:
        return None
    m = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", str(text).replace(" ", " "))
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def hhmm_to_min(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def in_window(hhmm, hora_min=None, hora_max=None):
    t = hhmm_to_min(hhmm)
    if hora_min and t < hhmm_to_min(hora_min):
        return False
    if hora_max and t > hhmm_to_min(hora_max):
        return False
    return True


def result(source, items, ok=True, note=None, unit="por persona"):
    """Formato común de resultado de una fuente para un tramo."""
    items = sorted([i for i in items if i.get("precio") is not None], key=lambda i: i["precio"])
    return {
        "fuente": source,
        "ok": ok,
        "nota": note,
        "unidad": unit,
        "mejor": items[0]["precio"] if items else None,
        "items": items,
    }


def failed(source, err):
    return result(source, [], ok=False, note=f"Error: {err}"[:300])


class Browser:
    """Contexto Playwright reutilizable entre fuentes."""

    def __init__(self):
        self._pw = None
        self.browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        return self

    async def __aexit__(self, *exc):
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    async def context(self, **kw):
        return await self.browser.new_context(
            user_agent=UA, locale="es-ES", viewport={"width": 1280, "height": 900}, **kw)


async def with_retry(coro_factory, attempts=2, delay=5):
    last = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except Exception as e:  # noqa: BLE001
            last = e
            if i + 1 < attempts:
                await asyncio.sleep(delay)
    raise last


# --- codificación del parámetro "ts" de Google Hotels (protobuf) ---
def _varint(v):
    out = b""
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def _field(f, wt, payload):
    return _varint((f << 3) | wt) + payload


def _vi(f, v):
    return _field(f, 0, _varint(v))


def _msg(f, b):
    return _field(f, 2, _varint(len(b)) + b)


def _date(f, iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return _msg(f, _vi(1, y) + _vi(2, m) + _vi(3, d))


def google_hotels_ts(checkin, checkout, adults, currency="EUR"):
    guests = b"".join(_msg(1, _vi(1, 3)) for _ in range(adults)) + _vi(2, 0)
    body = (_vi(1, 1) + _msg(2, guests)
            + _msg(3, _msg(2, _msg(2, _date(1, checkin) + _date(2, checkout) + _vi(3, 1)) + _msg(6, _vi(2, 0))))
            + _msg(5, _msg(1, _msg(7, currency.encode())) + _msg(3, b"")))
    return base64.urlsafe_b64encode(body).decode().rstrip("=")
