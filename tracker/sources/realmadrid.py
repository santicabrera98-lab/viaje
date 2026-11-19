"""Real Madrid: API pública del calendario (diaryV2) con precio mínimo y estado de venta de cada partido en el Bernabéu."""
import asyncio
import datetime as dt

import requests

from tracker.common import UA, result, failed

URL = ("https://publish.realmadrid.com/graphql/execute.json/realmadridmastersite/diaryV2"
       "%3BfromDate={desde}T00:00:00.000Z%3BtoDate={hasta}T23:59:00.000Z"
       "%3Balang=/content/dam/portals/realmadrid-com/es-es/sports/")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _get(url):
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json",
                                   "Origin": "https://www.realmadrid.com", "Referer": "https://www.realmadrid.com/"},
                     timeout=40)
    r.raise_for_status()
    return r.json()


def _fecha_local(iso):
    """'2027-02-28T20:00:00.000Z' -> datetime en hora de Madrid."""
    try:
        from zoneinfo import ZoneInfo
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return t.astimezone(ZoneInfo("Europe/Madrid"))
    except Exception:  # noqa: BLE001
        return None


async def fetch(browser, tramo):
    conf = tramo["realmadrid"]
    y, m = conf["mes"].split("-")
    desde = f"{y}-{m}-01"
    hasta = (dt.date(int(y), int(m), 28) + dt.timedelta(days=7)).replace(day=1).isoformat()
    try:
        data = await asyncio.to_thread(_get, URL.format(desde=desde, hasta=hasta))
    except Exception as e:  # noqa: BLE001
        return failed("realmadrid", e)
    partido = None
    for it in (data.get("data", {}).get("matchList", {}) or {}).get("items", []):
        if str(it.get("id")) == str(conf.get("match_id")) or (it.get("slug") or "").startswith(conf.get("slug", "\0")):
            partido = it
            break
    if not partido:
        return result("realmadrid", [], note="El partido no aparece en el calendario del club para ese mes")
    info = partido.get("ticketInformation") or {}
    # fecha y hora
    f = _fecha_local(partido.get("dateTime") or "")
    if partido.get("isScheduled") and f:
        cuando = f"{DIAS[f.weekday()]} {f.day}/{f.month} {f:%H:%M}"
    elif f:
        cuando = f"provisorio {DIAS[f.weekday()]} {f.day}/{f.month}; día y hora por confirmar (La Liga lo fija 2 a 3 semanas antes)"
    else:
        cuando = "fecha por confirmar"
    partes = [f"Partido: {cuando}."]
    venta = (info.get("generalPublicCollective") or {}).get("startDateTime")
    v = _fecha_local(venta) if venta else None
    if v:
        partes.append(f"Venta al público general desde el {DIAS[v.weekday()]} {v.day}/{v.month} {v:%H:%M}.")
    items = []
    precio = info.get("fromPrice") if info.get("fromPrice") is not None else partido.get("fromPrice")
    link = info.get("ticketsLink") or partido.get("ticketsLink")
    if info.get("soldOut") or partido.get("soldOut"):
        partes.append("Aforo general agotado.")
    elif precio is not None:
        items.append({"etiqueta": "Aforo general, entrada más barata (realmadrid.com)", "precio": float(precio),
                      "url": link, "cuando": cuando, "venta": "a la venta"})
    else:
        partes.append("Aforo general todavía no a la venta (el club abre unos 4 días antes del partido; socios y Madridistas antes).")
    vip = info.get("fromPriceVIP") or partido.get("fromPriceVIP")
    if vip:
        partes.append(f"VIP desde {int(vip)} €.")
    return result("realmadrid", items, note=" ".join(partes), unit="por persona")
