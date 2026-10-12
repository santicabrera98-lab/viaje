"""Renfe (AVE / Avlo / Alvia...): búsqueda directa en venta.renfe.com."""
import re

from tracker.common import in_window, parse_eur, result, failed

ESTACIONES = {
    "madrid": ("MADRI", "Madrid (TODAS)"),
    "valencia": ("VALEN", "Valencia (TODAS)"),
    "barcelona": ("BARCE", "Barcelona (TODAS)"),
}

FORM = """<form id="f" method="POST" action="https://venta.renfe.com/vol/buscarTren.do">
<input name="tipoBusqueda" value="autocomplete"><input name="currenLocation" value="menuBusqueda"><input name="vengoderenfecom" value="SI">
<input name="desOrigen" value="{odesc}"><input name="desDestino" value="{ddesc}"><input name="cdgoOrigen" value="{o}"><input name="cdgoDestino" value="{d}">
<input name="idiomaBusqueda" value="ES"><input name="FechaIdaSel" value="{f}"><input name="FechaVueltaSel" value=""><input name="_fechaIdaVisual" value="{f}"><input name="_fechaVueltaVisual" value="">
<input name="adultos_" value="{n}"><input name="ninos_" value="0"><input name="ninosMenores" value="0"><input name="numJoven" value=""><input name="numDorada" value="">
<input name="codPromocional" value=""><input name="plazaH" value="false"><input name="sinEnlace" value="false"><input name="asistencia" value="false"><input name="franjaHoraI" value=""><input name="franjaHoraV" value="">
</form>"""


async def fetch(browser, tramo):
    o, odesc = ESTACIONES[tramo["origen"]]
    d, ddesc = ESTACIONES[tramo["destino"]]
    y, m, dd = tramo["fecha"].split("-")
    fecha = f"{dd}/{m}/{y}"
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        await page.goto("https://www.renfe.com/es/es", wait_until="domcontentloaded", timeout=60000)
        await page.set_content(FORM.format(o=o, odesc=odesc, d=d, ddesc=ddesc, f=fecha, n=tramo["personas"]))
        async with page.expect_navigation(timeout=60000):
            await page.evaluate("document.getElementById('f').submit()")
        await page.wait_for_timeout(8000)
        body = await page.inner_text("body")
        rows = await page.query_selector_all("div.selectedTren")
        items = []
        for r in rows:
            labels = await r.eval_on_selector_all("span[aria-label]", "els => els.map(e => e.getAttribute('aria-label'))")
            txt = " ".join(labels)
            mt = re.search(r"salida a las (\d{1,2}:\d{2}) y llegada a las (\d{1,2}:\d{2})", txt)
            tipo = re.search(r"Tipo de tren: ([^.]+)\.", txt)
            if not mt:
                continue
            dep, arr = mt.group(1).zfill(5), mt.group(2).zfill(5)
            if not in_window(dep, tramo.get("hora_min"), tramo.get("hora_max")):
                continue
            precio_el = await r.query_selector(".precio-final")
            precio = parse_eur(await precio_el.inner_text()) if precio_el else None
            completo = "completo" in (await r.inner_text()).lower()
            items.append({"etiqueta": f"{(tipo.group(1) if tipo else 'Renfe').strip()} {dep}→{arr}",
                          "precio": precio, "salida": dep, "llegada": arr,
                          "operador": "Renfe", "completo": completo})
        note = None
        if not rows:
            if "no está disponible para la fecha" in body or "no disponemos" in body:
                note = "Renfe todavía no abrió la venta para esta fecha"
            else:
                note = "Sin resultados (estructura de página desconocida)"
        elif not items:
            note = "Hay trenes, pero ninguno en la franja horaria pedida"
        return result("renfe", items, note=note)
    except Exception as e:  # noqa: BLE001
        return failed("renfe", e)
    finally:
        await ctx.close()
