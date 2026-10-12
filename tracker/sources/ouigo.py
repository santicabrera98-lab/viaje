"""Ouigo: usa la API que carga el propio buscador web (el token lo obtiene la página)."""
import json

from tracker.common import in_window, result, failed

ESTACIONES = {"madrid": "MT1", "valencia": "7103216", "barcelona": "7171801"}
WIDGET = "https://falbala-cdn-sse-prod.ouigo.com/?locale=es-ES"
API = "https://mdw02.api-es.ouigo.com"
JS = """async ([url, body, tok]) => {
  const r = await fetch(url, {method: 'POST', headers: {'Authorization': 'Bearer ' + tok,
    'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify(body)});
  const t = await r.text(); return [r.status, t];
}"""


async def _token(page):
    tok = {}

    async def on_resp(r):
        if "Token/login" in r.url and r.status == 200:
            try:
                tok["t"] = (await r.json())["token"]
            except Exception:  # noqa: BLE001
                pass

    page.on("response", on_resp)
    await page.goto(WIDGET, wait_until="domcontentloaded", timeout=60000)
    for _ in range(40):
        if tok:
            return tok["t"]
        await page.wait_for_timeout(500)
    raise RuntimeError("no se obtuvo token de la web de Ouigo")


async def fetch(browser, tramo):
    n = tramo["personas"]
    o, d = ESTACIONES[tramo["origen"]], ESTACIONES[tramo["destino"]]
    pax = [{"type": "A"} for _ in range(n)]
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        tok = await _token(page)
        status, text = await page.evaluate(JS, [f"{API}/api/Sale/journeysearch",
                                                {"origin": o, "destination": d, "passengers": pax,
                                                 "outbound_date": tramo["fecha"], "direction": "outbound"}, tok])
        items, note = [], None
        if status == 204 or not text.strip():
            # Sin viajes: puede ser que la venta no esté abierta. Consultamos el calendario para saber hasta cuándo hay.
            y, m, _ = tramo["fecha"].split("-")
            st2, t2 = await page.evaluate(JS, [f"{API}/api/Calendar/prices",
                                               {"origin": o, "destination": d, "passengers": pax, "direction": "outbound",
                                                "begin": f"{y}-{m}-01", "end": tramo["fecha"]}, tok])
            note = "Ouigo todavía no abrió la venta para esta fecha"
            if st2 == 200:
                try:
                    days = [x for x in json.loads(t2) if x.get("price") is not None]
                    if days:
                        note += f" (último día a la venta: {max(x['date'] for x in days)})"
                except Exception:  # noqa: BLE001
                    pass
            return result("ouigo", [], note=note)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {text[:120]}")
        data = json.loads(text)
        for j in data.get("outbound", []):
            segs = j.get("segments") or []
            if not segs:
                continue
            dep = segs[0]["departure_station"]["departure_timestamp"][11:16]
            arr = segs[-1]["arrival_station"]["arrival_timestamp"][11:16]
            if not in_window(dep, tramo.get("hora_min"), tramo.get("hora_max")):
                continue
            total = j.get("price")
            precio = round(float(total) / n, 2) if total is not None else None
            origen = segs[0]["departure_station"]["name"].split(" - ")[0]
            items.append({"etiqueta": f"Ouigo {dep}→{arr} ({segs[0]['departure_station']['name']})",
                          "precio": precio, "salida": dep, "llegada": arr, "operador": "Ouigo",
                          "completo": bool(j.get("full")), "origen": origen})
        if data.get("outbound") and not items:
            note = "Hay trenes, pero ninguno en la franja horaria pedida"
        elif not data.get("outbound"):
            note = "Ouigo no ofrece este trayecto (o no hay trenes ese día)"
        return result("ouigo", items, note=note)
    except Exception as e:  # noqa: BLE001
        return failed("ouigo", e)
    finally:
        await ctx.close()
