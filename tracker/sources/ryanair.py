"""Ryanair: precios por vuelo capturando la respuesta de disponibilidad que carga la web."""
import asyncio
import json

import requests

from tracker.common import UA, in_window, result, failed

TIMETABLE = "https://www.ryanair.com/api/timtbl/3/schedules/{o}/{d}/years/{y}/months/{m}"
SELECT_URL = ("https://www.ryanair.com/es/es/trip/flights/select?adults={n}&teens=0&children=0&infants=0"
              "&dateOut={out}&dateIn={back}&isConnectedFlight=false&discount=0&promoCode=&isReturn=true"
              "&originIata={o}&destinationIata={d}&tpAdults={n}&tpTeens=0&tpChildren=0&tpInfants=0"
              "&tpStartDate={out}&tpEndDate={back}&tpDiscount=0&tpPromoCode=&tpOriginIata={o}&tpDestinationIata={d}")
AEROPUERTOS = {"FCO": "Fiumicino", "CIA": "Ciampino", "VLC": "Valencia"}


def route_exists(o, d, fecha):
    """Usa el horario público para saber si la ruta opera ese día."""
    y, m, day = fecha.split("-")
    r = requests.get(TIMETABLE.format(o=o, d=d, y=int(y), m=int(m)), headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        return None
    for dd in r.json().get("days", []):
        if dd["day"] == int(day):
            return dd["flights"]
    return []


async def _fetch_availability(browser, o, d, n, out, back):
    ctx = await browser.context()
    page = await ctx.new_page()
    captured = {}

    async def on_resp(r):
        if "/api/booking/v4/" in r.url and "availability" in r.url and r.status == 200:
            try:
                captured["data"] = await r.json()
            except Exception:  # noqa: BLE001
                pass

    page.on("response", on_resp)
    try:
        await page.goto(SELECT_URL.format(n=n, out=out, back=back, o=o, d=d), wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            if "data" in captured:
                break
            await page.wait_for_timeout(1000)
    finally:
        await ctx.close()
    if "data" not in captured:
        raise RuntimeError("la web no devolvió disponibilidad (posible bloqueo)")
    return captured["data"]


def _flights_from(data, o, d, fecha):
    out = []
    for trip in data.get("trips", []):
        if trip.get("origin") != o or trip.get("destination") != d:
            continue
        for day in trip.get("dates", []):
            if not day.get("dateOut", "").startswith(fecha):
                continue
            for f in day.get("flights", []):
                fare = f.get("regularFare") or {}
                fares = fare.get("fares") or []
                precio = None
                for x in fares:
                    if x.get("type") == "ADT":
                        precio = x.get("amount")
                if precio is None and fares:
                    precio = fares[0].get("amount")
                dep = f["time"][0][11:16]
                arr = f["time"][1][11:16]
                out.append({
                    "etiqueta": f"{f.get('flightNumber','').replace(' ', '')} {dep}→{arr} ({o}→{d} {AEROPUERTOS.get(d, d)})",
                    "precio": precio, "salida": dep, "llegada": arr,
                    "aeropuerto": d if d != "VLC" else o,
                    "asientos": f.get("faresLeft"),
                })
    return out


async def fetch(browser, tramo):
    n = tramo["personas"]
    ida, vuelta = tramo["ida"], tramo["vuelta"]
    items, notes = [], []
    try:
        for dest in ida["destinos"]:
            sched = await asyncio.to_thread(route_exists, ida["origen"], dest, ida["fecha"])
            if not sched:
                notes.append(f"{ida['origen']}→{dest}: sin vuelos ese día")
                continue
            data = await _fetch_availability(browser, ida["origen"], dest, n, ida["fecha"], vuelta["fecha"])
            for f in _flights_from(data, ida["origen"], dest, ida["fecha"]):
                f["tramo"] = "ida"
                f["nocturno"] = in_window(f["salida"], ida.get("hora_min"))
                items.append(f)
            for f in _flights_from(data, dest, vuelta["destino"], vuelta["fecha"]):
                f["tramo"] = "vuelta"
                items.append(f)
    except Exception as e:  # noqa: BLE001
        return failed("ryanair", e)
    # Mejor combinación: ida nocturna más barata + vuelta más barata
    idas = [i for i in items if i["tramo"] == "ida" and i.get("precio") is not None]
    idas_noche = [i for i in idas if i.get("nocturno")] or idas
    vueltas = [i for i in items if i["tramo"] == "vuelta" and i.get("precio") is not None]
    combo = None
    if idas_noche and vueltas:
        a = min(idas_noche, key=lambda i: i["precio"])
        b = min(vueltas, key=lambda i: i["precio"])
        combo = {"etiqueta": f"Mejor combo: {a['etiqueta']} + {b['etiqueta']}",
                 "precio": round(a["precio"] + b["precio"], 2), "combo": True,
                 "ida": a["etiqueta"], "vuelta": b["etiqueta"]}
    res = result("ryanair", items, note="; ".join(notes) or None, unit="por persona (tarifa Basic, sin equipaje)")
    if combo:
        res["mejor"] = combo["precio"]
        res["combo"] = combo
    res["items"] = sorted(items, key=lambda i: (i["tramo"] != "ida", i["precio"] if i["precio"] is not None else 1e9))
    return res
