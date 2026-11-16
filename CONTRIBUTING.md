# Contributing

Thanks for helping improve Map Renderer.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r src/requirements.txt
python src/server.py
```

## Before opening a pull request

- Keep changes focused and document user-visible behavior.
- Run `python -m py_compile src/server.py`.
- Do not commit generated exports, virtual environments, credentials, or local configuration.
- Preserve OpenStreetMap and Copernicus attribution requirements.

Please include reproduction steps for bugs and screenshots for significant interface changes.
