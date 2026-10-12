"""Hostelworld: listado de hostels de la ciudad con precio 'desde' por persona y noche."""
import re

from tracker.common import load_cache, parse_eur, result, failed, save_cache

MAX_DETALLE = 12  # cuántos hostels (los más baratos) se abren para leer dirección y recepción 24 h


def _zona(direccion):
    d = (direccion or "").lower()
    claves = {
        "Monti": ["monti", "via cavour", "via panisperna", "via dei serpenti", "via urbana", "via leonina", "madonna dei monti"],
        "Termini": ["termini", "via marsala", "via principe amedeo", "via gioberti", "via cavour 1", "via varese", "via magenta", "via palestro", "castro pretorio", "via vicenza", "via volturno", "via marghera", "esquilino", "via dello statuto", "piazza vittorio"],
        "San Lorenzo": ["san lorenzo", "via tiburtina", "via dei volsci", "via dei sabelli", "via dei marsi", "via dei reti"],
        "San Giovanni": ["san giovanni", "via merulana", "appia nuova", "via la spezia", "via taranto", "via emanuele filiberto", "manzoni"],
    }
    for zona, kws in claves.items():
        if any(k in d for k in kws):
            return zona
    return None


# cajas aproximadas (lat_min, lat_max, lng_min, lng_max) de las zonas pedidas
ZONAS = {
    "Monti": (41.888, 41.899, 12.484, 12.498),
    "Termini": (41.895, 41.907, 12.494, 12.512),
    "San Lorenzo": (41.893, 41.906, 12.512, 12.527),
    "San Giovanni": (41.878, 41.893, 12.498, 12.516),
}


def _zona_coords(coords):
    if not coords:
        return None
    lat, lng = coords
    for zona, (a, b, c, d) in ZONAS.items():
        if a <= lat <= b and c <= lng <= d:
            return zona
    return None


async def _detalle(browser, url, checkin, checkout, n):
    """Abre la página del hostel y devuelve (dirección, recepción 24 h)."""
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        await page.goto(f"{url}?from={checkin}&to={checkout}&guests={n}&currency=EUR",
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        html = await page.content()
        m = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', html)
        direccion = m.group(1).strip() if m else None
        if not direccion:
            txt = await page.inner_text("body")
            m = re.search(r"Location\n([^\n]*(?:Rome|Roma)[^\n]*)", txt)
            direccion = m.group(1).strip() if m else None
        rec24 = bool(re.search(r'"name"\s*:\s*"24 Hour Reception"\s*,\s*"value"\s*:\s*true', html))
        lat = re.search(r'"latitude"\s*:\s*"?(-?\d+\.\d+)', html)
        lng = re.search(r'"longitude"\s*:\s*"?(-?\d+\.\d+)', html)
        coords = (float(lat.group(1)), float(lng.group(1))) if lat and lng else None
        return direccion, rec24, coords
    finally:
        await ctx.close()


async def fetch(browser, tramo):
    base = tramo["hostelworld"]["url"]
    n, ci, co = tramo["personas"], tramo["checkin"], tramo["checkout"]
    noches = tramo["noches"]
    cache = load_cache()
    det = cache.setdefault("hostelworld_detalle", {})
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        await page.goto(f"{base}?from={ci}&to={co}&guests={n}&currency=EUR", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        # cargar más resultados haciendo scroll
        for _ in range(6):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(800)
        cards = await page.query_selector_all("a.property-card-container")
        items, seen = [], set()
        for c in cards:
            href = await c.get_attribute("href")
            if not href or href in seen:
                continue
            seen.add(href)
            name_el = await c.query_selector(".property-name")
            nombre = (await name_el.inner_text()).strip() if name_el else "?"
            score_el = await c.query_selector(".score")
            score = (await score_el.inner_text()).strip() if score_el else None
            txt = await c.inner_text()
            priv = re.search(r"Privates From\s*€?([\d.,]+)", txt)
            dorm = re.search(r"Dorms From\s*€?([\d.,]+)", txt)
            desde = re.search(r"From\s*€([\d.,]+)", txt)
            dist = re.search(r"([\d.]+km from city centre)", txt)
            precio = parse_eur(desde.group(1) if desde else None)
            if precio is None:
                continue
            items.append({
                "etiqueta": nombre, "precio": precio, "url": href.split("?")[0],
                "privada": parse_eur(priv.group(1)) if priv else None,
                "compartida": parse_eur(dorm.group(1)) if dorm else None,
                "puntuacion": score, "distancia": dist.group(1) if dist else None,
                "total_persona": round(precio * noches, 2),
            })
    except Exception as e:  # noqa: BLE001
        await ctx.close()
        return failed("hostelworld", e)
    await ctx.close()
    items.sort(key=lambda i: i["precio"])
    for it in items[:MAX_DETALLE]:
        key = it["url"]
        if key not in det:
            try:
                direccion, rec24, coords = await _detalle(browser, key, ci, co, n)
                det[key] = {"direccion": direccion, "recepcion24": rec24, "coords": coords}
            except Exception:  # noqa: BLE001
                det[key] = {"direccion": None, "recepcion24": None, "coords": None}
        it.update(det[key])
        it["zona"] = _zona_coords(it.get("coords")) or _zona(it.get("direccion"))
    save_cache(cache)
    return result("hostelworld", items, unit=f"por persona y noche (×{noches} noches = total_persona)")
