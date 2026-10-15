"""Google Flights: todas las aerolíneas de la ruta. Cada fila es una ida con su vuelta más barata (precio ida+vuelta por persona)."""
import base64
import re

from tracker.common import _msg, _vi, in_window, result, failed

URL = "https://www.google.com/travel/flights?tfs={tfs}&hl=es&curr=EUR&gl=es&tfu=EgQIABABIgA"


def _tfs(o, d, out, back, adults=1, max_stops=0):
    """Parámetro 'tfs' de Google Flights (protobuf en base64): ida y vuelta, directos, turista."""
    def tramo(date, a, b):
        return _msg(3, bytes([0x12, len(date)]) + date.encode() + _vi(5, max_stops)
                    + _msg(13, _msg(2, a.encode())) + _msg(14, _msg(2, b.encode())))
    body = tramo(out, o, d) + tramo(back, d, o) + b"".join(_vi(8, 1) for _ in range(adults)) + _vi(9, 1) + _vi(19, 1)
    return base64.urlsafe_b64encode(body).decode().rstrip("=")


FILA = re.compile(r"^(\d{1,2}:\d{2})\s*\|\s*–\s*\|\s*(\d{1,2}:\d{2})(\+\d)?\s*\|\s*(.+?)\s*\|\s*(\d+\s*h[^|]*)\|\s*(\w{3})–(\w{3})\s*\|\s*([^|]+?)\s*\|.*?(\d[\d.]*)\s*€")


async def _buscar(browser, o, d, out, back, n):
    ctx = await browser.context()
    page = await ctx.new_page()
    try:
        await page.goto(URL.format(tfs=_tfs(o, d, out, back, n)), wait_until="domcontentloaded", timeout=60000)
        txt = ""
        for _ in range(15):
            await page.wait_for_timeout(3000)
            txt = await page.inner_text("body")
            if "Obteniendo resultados" not in txt and "Cargando resultados" not in txt:
                break
        if "tráfico inusual" in txt or "unusual traffic" in txt or "captcha" in txt.lower():
            raise RuntimeError("Google pidió captcha")
        if "No hemos encontrado" in txt or "no se han encontrado vuelos" in txt.lower():
            return []
        filas = []
        for ul in await page.query_selector_all("ul"):
            t = await ul.inner_text()
            if "ida y vuelta" not in t:
                continue
            for li in await ul.query_selector_all(":scope > li"):
                linea = (await li.inner_text()).replace("\n", " | ")
                m = FILA.search(linea)
                if m:
                    filas.append(m.groups())
            if filas:
                break
        return filas
    finally:
        await ctx.close()


async def fetch(browser, tramo):
    ida, vuelta, n = tramo["ida"], tramo["vuelta"], tramo["personas"]
    items, notas = [], []
    try:
        for dest in ida["destinos"]:
            filas = await _buscar(browser, ida["origen"], dest, ida["fecha"], vuelta["fecha"], n)
            if not filas:
                notas.append(f"{ida['origen']}→{dest}: sin vuelos directos")
                continue
            for dep, arr, mas, aerolinea, dur, o, d, escalas, precio in filas:
                aerolinea = re.sub(r"Operado por.*", "", aerolinea).strip()
                items.append({
                    "etiqueta": f"{aerolinea} {dep.zfill(5)}→{arr.zfill(5)}{mas or ''} ({o}→{d}) + vuelta más barata",
                    "precio": float(precio.replace(".", "")), "salida": dep.zfill(5), "llegada": arr.zfill(5),
                    "aeropuerto": d, "aerolinea": aerolinea, "tramo": "ida y vuelta",
                    "nocturno": in_window(dep.zfill(5), ida.get("hora_min")),
                })
    except Exception as e:  # noqa: BLE001
        return failed("google_flights", e)
    res = result("google_flights", items, note="; ".join(notas) or None, unit="ida y vuelta por persona (ida elegida + vuelta más barata)")
    noct = [i for i in items if i["nocturno"]]
    if noct:
        mejor = min(noct, key=lambda i: i["precio"])
        res["mejor"] = mejor["precio"]
        res["combo"] = {"etiqueta": mejor["etiqueta"], "precio": mejor["precio"], "ida": mejor["etiqueta"], "vuelta": "la más barata según Google"}
    return res
