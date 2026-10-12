# Rastreador de precios: viaje a España, febrero 2027

Bot que consulta cada 6 horas los precios de los vuelos, trenes y alojamientos del viaje,
guarda el historial en este repositorio y publica una web donde se ve, de un vistazo,
si conviene comprar.

## Cómo verlo

La web se publica con GitHub Pages en `https://<usuario>.github.io/viaje/`.
Entrás, mirás el resumen de arriba (una tarjeta por tramo con semáforo) y, si algo
está en verde, bajás al detalle para ver el vuelo, tren u hotel concreto y el enlace para comprar.

## Puesta en marcha (una sola vez)

1. En GitHub, en el repositorio: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. En **Actions**, abrí el workflow "Rastrear precios y publicar web" y tocá **Run workflow**
   para la primera corrida. Desde ahí corre solo cada 6 horas.
3. Si el repositorio es privado, GitHub Pages requiere plan Pro. En público funciona con la cuenta gratuita.

## Qué rastrea y de dónde

| Tramo | Fuente | Cómo |
|---|---|---|
| Vuelo Valencia ⇄ Roma (4 personas) | Ryanair | Precio por vuelo que carga la web de Ryanair; marca el vuelo nocturno y el aeropuerto (Fiumicino / Ciampino) |
| Trenes Madrid–Valencia–Barcelona (2 personas) | Renfe, Ouigo, FlixBus | Renfe: búsqueda directa. Ouigo: la API que usa su propio buscador. FlixBus: API pública, que además revende Iryo |
| Roma, hostel 4 noches | Hostelworld | Lista de hostels con precio por persona; abre los 12 más baratos para leer dirección, zona y si tienen recepción 24 h |
| Córdoba y Sevilla con estacionamiento, Madrid doble | Google Hotels | Listado con fechas y huéspedes fijados, filtrado por "con parking" |

**No se rastrean** porque sus webs bloquean robots: Booking, Trainline, Omio, Iryo directo (aparece vía FlixBus),
Alsa y BlaBlaCar. La web deja enlaces para revisarlos a mano.

Cuando una venta todavía no está abierta (Renfe y Ouigo suelen abrir entre 2 y 4 meses antes),
la fuente lo dice en la web y el bot sigue probando en cada corrida, así que el día que abra aparece el precio.

## Semáforo

- **Comprar**: el mejor precio actual está en o por debajo de la referencia fijada.
- **Mínimo histórico**: es el precio más bajo visto desde que empezó el rastreo.
- **Cerca**: a menos de 15 % de la referencia.
- **Esperar**: más caro.

## Cambiar fechas, personas o referencias

Todo está en `config/viaje.json`. Cada tramo tiene fecha, personas, franja horaria (`hora_min`, `hora_max`),
precio de referencia y fuentes. Al hacer push el workflow corre y la web se actualiza.

## Correr en local

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m tracker.run                 # todas las fuentes
python -m tracker.run tren_mad_vlc    # solo un tramo
python -m tracker.run --solo-web      # regenerar docs/data.json sin consultar nada
python -m http.server -d docs 8000    # ver la web en http://localhost:8000
```

## Estructura

- `config/viaje.json`: definición del viaje.
- `tracker/sources/*.py`: una fuente por archivo; cada una devuelve el mismo formato.
- `tracker/run.py`: corre todo, agrega al historial (`data/history.jsonl`) y genera `docs/data.json`.
- `docs/index.html`: la web (estática, lee `data.json`).
- `.github/workflows/rastrear.yml`: la corrida programada y la publicación en Pages.
