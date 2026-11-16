# Map Renderer

Map Renderer is a local web app for creating customizable topographic contour maps and OpenStreetMap-based water maps. Exports are available as PNG or SVG.

## Features

- Topographic contour maps from Copernicus DEM data.
- Water maps from OpenStreetMap hydrography.
- Lake, wetland, basin, river, stream, canal, and riverbank geometries.
- Optional water-body fills or outline-only rendering.
- PNG and SVG export.
- Interactive bounding-box selection and place search.
- Touch-friendly map selection.
- Saved browser preferences and last map position.

## Requirements

- Python 3.11 or newer.
- Internet access for Copernicus DEM, OpenStreetMap, Overpass, Nominatim, and Leaflet resources.
- The native dependencies required by `rasterio`, `shapely`, and `pyproj` on your platform.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r src/requirements.txt
python src/server.py
```

Open <http://127.0.0.1:8002> in a browser.

To test from another device on the same network, the server listens on all interfaces by default:

```bash
http://YOUR_COMPUTER_IP:8002
```

Use `TOPO_HOST` and `TOPO_PORT` to override the bind address or port.

## Data and attribution

- Map tiles and hydrography: [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the [ODbL](https://opendatacommons.org/licenses/odbl/).
- Elevation: Copernicus DEM. Review the [Copernicus Data Space terms](https://dataspace.copernicus.eu/).
- Map interaction: [Leaflet](https://leafletjs.com/).

Please retain the required attribution when publishing or redistributing generated maps.

## Project layout

```text
src/
├── app.js             # Browser application
├── index.html         # Web interface
├── server.py          # Local API and map renderer
├── styles.css         # Interface styles
└── requirements.txt   # Python dependencies
```

## Limitations

The app depends on public data services. Overpass requests can be slow or temporarily unavailable, especially for relation-heavy water queries. Large bounding boxes may exceed service or rendering limits.

GitHub Pages can host the static interface, but it cannot run the Python renderer. A public deployment therefore needs a separate Python-compatible backend.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
