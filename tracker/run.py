"""Ejecuta todas las fuentes, guarda el historial y genera docs/data.json para la web."""
import asyncio
import importlib
import json
import sys

from tracker.common import DATA_DIR, HISTORY_PATH, ROOT, Browser, load_config, now_iso

DOCS_DATA = ROOT / "docs" / "data.json"


async def run_tramo(browser, tramo):
    out = []
    for src in tramo["fuentes"]:
        mod = importlib.import_module(f"tracker.sources.{src}")
        print(f"[{tramo['id']}] {src} ...", flush=True)
        try:
            r = await asyncio.wait_for(mod.fetch(browser, tramo), timeout=420)
        except Exception as e:  # noqa: BLE001
            r = {"fuente": src, "ok": False, "nota": f"Error: {e}"[:300], "unidad": "", "mejor": None, "items": []}
        print(f"[{tramo['id']}] {src}: ok={r['ok']} mejor={r['mejor']} items={len(r['items'])} {r.get('nota') or ''}", flush=True)
        out.append(r)
    return out


async def main(only=None):
    cfg = load_config()
    ts = now_iso()
    registros = []
    async with Browser() as browser:
        for tramo in cfg["tramos"]:
            if only and tramo["id"] not in only:
                continue
            for r in await run_tramo(browser, tramo):
                registros.append({"ts": ts, "tramo": tramo["id"], **r})
    DATA_DIR.mkdir(exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    build_site_data(cfg)


def _mejor_tramo(fuentes):
    """Mejor precio comparable del tramo (vuelos: combo ida+vuelta; trenes: por persona; hoteles: ver unidad)."""
    vals = [f["mejor"] for f in fuentes if f.get("ok") and f.get("mejor") is not None]
    return min(vals) if vals else None


def build_site_data(cfg=None):
    cfg = cfg or load_config()
    hist = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                hist.append(json.loads(line))
    por_tramo = {}
    for tramo in cfg["tramos"]:
        regs = [h for h in hist if h["tramo"] == tramo["id"]]
        # serie: por corrida (ts), mejor precio del tramo
        corridas = {}
        for r in regs:
            corridas.setdefault(r["ts"], []).append(r)
        serie = []
        for ts in sorted(corridas):
            m = _mejor_tramo(corridas[ts])
            serie.append({"ts": ts, "mejor": m, "fuentes": {r["fuente"]: r["mejor"] for r in corridas[ts]}})
        ultimo_ts = max(corridas) if corridas else None
        ultimo = corridas.get(ultimo_ts, [])
        # última corrida con datos válidos por fuente (si la última falló, mostrar la anterior)
        ultimo_valido = {}
        for ts in sorted(corridas, reverse=True):
            for r in corridas[ts]:
                if r["fuente"] not in ultimo_valido and r["ok"] and r["items"]:
                    ultimo_valido[r["fuente"]] = r
        con_datos = [s["mejor"] for s in serie if s["mejor"] is not None]
        minimo = min(con_datos) if con_datos else None
        actual = _mejor_tramo(ultimo)
        ref = (tramo.get("referencia") or {}).get("valor")
        semaforo = "sin_datos"
        if actual is None and ultimo and all(r["ok"] and not r["items"] for r in ultimo):
            semaforo = "no_abierto"   # las fuentes respondieron pero todavía no hay nada a la venta
        if actual is not None:
            if ref is not None and actual <= ref:
                semaforo = "comprar"
            elif len(con_datos) >= 3 and minimo is not None and actual <= minimo * 1.02:
                semaforo = "minimo"
            elif ref is not None and actual <= ref * 1.15:
                semaforo = "cerca"
            else:
                semaforo = "esperar"
        por_tramo[tramo["id"]] = {
            **tramo,
            "ultimo_ts": ultimo_ts,
            "fuentes_ultimo": ultimo,
            "fuentes_ultimo_valido": ultimo_valido,
            "serie": serie,
            "minimo_historico": minimo,
            "actual": actual,
            "semaforo": semaforo,
        }
    DOCS_DATA.parent.mkdir(exist_ok=True)
    DOCS_DATA.write_text(json.dumps({"generado": now_iso(), "moneda": cfg["moneda"], "tramos": por_tramo},
                                    ensure_ascii=False), encoding="utf-8")
    print(f"docs/data.json generado ({len(hist)} registros en historial)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--solo-web":
        build_site_data()
    else:
        asyncio.run(main(only=set(args) or None))
