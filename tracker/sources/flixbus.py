"""FlixBus: API pública de búsqueda."""
import asyncio
import datetime as dt
import json

import requests

from tracker.common import UA, in_window, result, failed

CIUDADES = {
    "madrid": "9a07bb38-3596-48eb-a857-18fd01199c62",
    "valencia": "fe6bf6e1-6198-4eec-8843-ab6001133840",
    "barcelona": "40e086ed-8646-11e6-9066-549f350fcb0c",
}
OPERADORES = {"iryosa": "Iryo", "flixbus": "FlixBus", "alsa": "Alsa", "mfb": "FlixBus"}
URL = ("https://global.api.flixbus.com/search/service/v4/search?from_city_id={o}&to_city_id={d}"
       "&departure_date={f}&products=%7B%22adult%22%3A{n}%7D&currency=EUR&locale=es&search_by=cities"
       "&include_after_midnight_rides=0")


def _get(url):
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=40)
    r.raise_for_status()
    return r.json()


async def fetch(browser, tramo):
    y, m, d = tramo["fecha"].split("-")
    url = URL.format(o=CIUDADES[tramo["origen"]], d=CIUDADES[tramo["destino"]], f=f"{d}.{m}.{y}", n=tramo["personas"])
    try:
        data = await asyncio.to_thread(_get, url)
    except Exception as e:  # noqa: BLE001
        return failed("flixbus", e)
    items = []
    for trip in data.get("trips", []):
        for key, r in trip.get("results", {}).items():
            try:
                dep_dt = dt.datetime.fromisoformat(r["departure"]["date"])
                arr_dt = dt.datetime.fromisoformat(r["arrival"]["date"])
            except Exception:  # noqa: BLE001
                continue
            if dep_dt.date().isoformat() != tramo["fecha"]:
                continue
            dep, arr = dep_dt.strftime("%H:%M"), arr_dt.strftime("%H:%M")
            if not in_window(dep, tramo.get("hora_min"), tramo.get("hora_max")):
                continue
            total = (r.get("price") or {}).get("total")
            if total is None:
                continue
            precio = round(float(total) / tramo["personas"], 2)
            legs = r.get("legs") or []
            ops = []
            for leg in legs:
                oid = leg.get("operator_id") or ""
                label = OPERADORES.get(oid) or (data.get("operators", {}).get(oid, {}) or {}).get("label") or "FlixBus"
                medio = "tren" if leg.get("means_of_transport") == "train" else "bus"
                ops.append(f"{label} ({medio})")
            op = " + ".join(dict.fromkeys(ops)) or "FlixBus (bus)"
            transbordo = " con transbordo" if len(legs) > 1 else ""
            items.append({"etiqueta": f"{op} {dep}→{arr}{transbordo} · vía FlixBus",
                          "precio": precio, "salida": dep, "llegada": arr, "operador": op,
                          "completo": r.get("status") not in (None, "available")})
    note = None if items else "Sin viajes publicados para esa fecha (FlixBus abre la venta unos meses antes)"
    return result("flixbus", items, note=note)
