"""API REST del prototipo (FastAPI).

Ejecutar:  uvicorn prevalida.api:app --reload
Variables: PREVALIDA_MOTOR=tesseract|textract|azure, TESSDATA_DIR, EMISOR_JSON, RAICES_FEA (rutas separadas por ':').
"""
from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from .bitacora import Bitacora
from .ocr import crear_motor
from .pipeline import Prevalidador
from .reglas import Contexto, MotorReglas, cargar_config
from .verificacion import RegistroEmisor

BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="Prevalidación documental – prototipo")

_motor_nombre = os.environ.get("PREVALIDA_MOTOR", "tesseract")
_motor = crear_motor(_motor_nombre, **({"tessdata": os.environ.get("TESSDATA_DIR", str(BASE / "tessdata"))}
                                        if _motor_nombre == "tesseract" else {}))
_prev = Prevalidador(
    _motor, MotorReglas(cargar_config(BASE / "config" / "reglas.yaml")),
    RegistroEmisor(os.environ.get("EMISOR_JSON", str(BASE / "corpus" / "emisor_simulado.json"))),
    [Path(p).read_bytes() for p in os.environ.get("RAICES_FEA", "").split(":") if p],
    Bitacora(os.environ.get("BITACORA_DB", ":memory:")),
)
_solicitudes: dict[str, dict] = {}


@app.post("/solicitudes")
def crear_solicitud(nombre: str = Form(...), numero_pasaporte: str = Form(""),
                    paises_residencia: str = Form("")):
    sid = str(uuid.uuid4())
    _solicitudes[sid] = {"ctx": Contexto(date.today(), nombre, numero_pasaporte,
                                         [p for p in paises_residencia.split(",") if p]), "documentos": []}
    _prev.bitacora.registrar(sid, "solicitante", "creacion", {"nombre": nombre})
    return {"id": sid}


@app.post("/solicitudes/{sid}/documentos")
async def cargar_documento(sid: str, tipo: str = Form(...), idioma: str = Form(...), pais: str = Form(""),
                           imagen: UploadFile = File(...), pdf: UploadFile | None = File(None)):
    if sid not in _solicitudes:
        raise HTTPException(404, "Solicitud no existe")
    s = _solicitudes[sid]
    img, doc_pdf = await imagen.read(), (await pdf.read() if pdf else None)
    # El OCR y la validación de firma son bloqueantes: se ejecutan fuera del bucle de eventos.
    r = await run_in_threadpool(_prev.procesar, sid, tipo, idioma, img, s["ctx"], doc_pdf, pais)
    s["documentos"].append(r)
    # Respuesta inmediata al solicitante: nunca bloquea el envío (RF-09).
    return {"estado": r.estado, "via": r.via,
            "mensajes": [h.mensaje for h in r.hallazgos], "puede_enviar": True}


@app.get("/solicitudes/{sid}")
def expediente(sid: str):
    """Vista del funcionario: datos extraídos, hallazgos y estado de cada documento (RF-10)."""
    if sid not in _solicitudes:
        raise HTTPException(404, "Solicitud no existe")
    s = _solicitudes[sid]
    return {"documentos": [{"tipo": d.tipo, "via": d.via, "estado": d.estado, "campos": d.campos,
                            "hallazgos": [h.__dict__ for h in d.hallazgos]} for d in s["documentos"]],
            "expediente": [h.__dict__ for h in _prev.completitud(s["documentos"], s["ctx"])],
            "bitacora_integra": _prev.bitacora.verificar(_ANCLAS[-1] if _ANCLAS else None)}


# Anclas externas de la bitácora (en producción: sello de tiempo de un tercero o WORM).
_ANCLAS: list[dict] = []


@app.post("/bitacora/ancla")
def anclar():
    _ANCLAS.append(_prev.bitacora.ancla())
    return _ANCLAS[-1]
