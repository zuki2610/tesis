"""Servidor para probar la maqueta en el navegador (por ejemplo, en GitHub Codespaces).

Levanta la API de la maqueta con el emisor simulado y la infraestructura de firma de la
demostración, y publica además el reporte de la demostración:

  /docs                 interfaz de la API: crear una solicitud y cargar documentos
  /demo/reporte.html    reporte de la demostración (lo genera scripts/demo_expediente.py)
  /demo/documentos/     documentos ficticios de la demostración, para descargarlos y cargarlos en /docs

Uso:
  python scripts/demo_expediente.py      # una vez, para generar los documentos y el reporte
  python scripts/servidor_demo.py        # luego abre el puerto 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEMO = Path(os.environ.get("DEMO_DIR", BASE / "demo")).resolve()
if not (DEMO / "_trabajo" / "emisor.json").exists():
    sys.exit("Falta la demostración: ejecuta primero  python scripts/demo_expediente.py")
os.environ.setdefault("EMISOR_JSON", str(DEMO / "_trabajo" / "emisor.json"))
os.environ.setdefault("RAICES_FEA", str(DEMO / "_trabajo" / "certs" / "raiz_acreditada.pem"))
os.environ.setdefault("TESSDATA_DIR", str(BASE / "tessdata"))
sys.path.insert(0, str(BASE))

import uvicorn  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from prevalida.api import app  # noqa: E402

app.mount("/demo", StaticFiles(directory=DEMO, html=True), name="demo")


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/demo/reporte.html")


if __name__ == "__main__":
    print("Reporte:  http://localhost:8000/demo/reporte.html")
    print("API:      http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
