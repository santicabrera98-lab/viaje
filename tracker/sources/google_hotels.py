"""Google Hotels: listado con precio por noche para las fechas y huéspedes dados."""
import re
from urllib.parse import quote

from tracker.common import google_hotels_ts, parse_eur, result, failed

PAGINAS = 2  # páginas de resultados de Google a leer
URL = "https://www.google.com/travel/search?q={q}&hl=es&gl=es&curr=EUR&ts={ts}"


async def fetch(browser, tramo):
    q = tramo["google_hotels"]["q"]
    ts = google_hotels_ts(tramo["checkin"], tramo["checkout"], tramo["personas"])
    url = URL.format(q=quote(q), ts=ts)
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(9000)
        body = await page.inner_text("body")
        if "unusual traffic" in body or "tráfico inusual" in body or "captcha" in body.lower():
            raise RuntimeError("Google pidió captcha")
        # verificar que las fechas aplicaron
        ci = await page.query_selector("input[aria-label*='Entrada']")
        fecha_ok = ci is not None and (await ci.get_attribute("value") or "") != ""
        # ordenar por precio más bajo (si el control existe)
        try:
            await page.click("button:has-text('Ordenar por')", timeout=5000)
            await page.wait_for_timeout(1000)
            await page.click("[role='menuitemradio']:has-text('Precio más bajo'), [role='menuitem']:has-text('Precio más bajo'), li:has-text('Precio más bajo')", timeout=5000)
            await page.wait_for_timeout(6000)
        except Exception:  # noqa: BLE001
            pass
        items, seen, sin_precio = [], set(), 0
        for pagina in range(PAGINAS):
            if pagina:
                try:
                    nxt = await page.query_selector("button[aria-label='Siguiente']")
                    if not nxt or await nxt.get_attribute("disabled") is not None:
                        break
                    await nxt.scroll_into_view_if_needed(timeout=5000)
                    await nxt.click(timeout=5000)
                    await page.wait_for_timeout(7000)
                except Exception:  # noqa: BLE001
                    break
            for _ in range(4):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(700)
            # esperar a que dejen de aparecer precios (cargan de a poco)
            prev = -1
            for _ in range(8):
                cnt = await page.evaluate("() => (document.body.innerText.match(/\\d\\s?€/g) || []).length")
                if cnt == prev:
                    break
                prev = cnt
                await page.wait_for_timeout(1500)
            heads = await page.query_selector_all("h2")
            for h in heads:
                r = await _parse_card(h, tramo, seen)
                if r == "sin_precio":
                    sin_precio += 1
                elif r:
                    items.append(r)
        note = None if fecha_ok else "No pude confirmar que Google aplicó las fechas; revisar"
        if sin_precio:
            note = (note + ". " if note else "") + f"{sin_precio} alojamientos sin precio para {tramo['personas']} huéspedes (excluidos)"
        return result("google_hotels", items, note=note, unit=f"por noche, {tramo['personas']} huéspedes (total = ×{tramo['noches']} noches)")
    except Exception as e:  # noqa: BLE001
        return failed("google_hotels", e)
    finally:
        await ctx.close()


async def _parse_card(h, tramo, seen):
    card = await h.evaluate_handle("e => e.closest('[jsname]')")
    if not card:
        return None
    txt = (await card.evaluate("e => e.innerText")) or ""
    if "Patrocinado" in txt[:40]:
        return None
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    if len(lines) < 2:
        return None
    nombre = lines[0]
    if nombre in seen or len(nombre) > 90:
        return None
    # el precio por noche va en una línea sola ("86 €"); ignoramos importes dentro de frases ("desayuno 6 €")
    m = re.search(r"^\s*(\d[\d.]*)\s*€\s*$", txt, re.M)
    if not m:
        return "sin_precio"
    seen.add(nombre)
    precio = parse_eur(m.group(1).replace(".", ""))
    rating = re.search(r"\n(\d,\d)\n", txt)
    estrellas = re.search(r"Hotel de (\d) estrella", txt)
    parking = "parcamiento" in txt.lower() or "parking" in txt.lower()
    link = await card.evaluate("e => { const a = e.querySelector('a[href*=\"/travel/hotels/entity\"]') || e.querySelector('a[href]'); return a ? a.href : null; }")
    return {"etiqueta": nombre, "precio": precio, "puntuacion": rating.group(1) if rating else None,
                  "estrellas": int(estrellas.group(1)) if estrellas else None,
                  "estacionamiento": parking, "url": link,
                  "total": round(precio * tramo["noches"], 2) if precio is not None else None}
