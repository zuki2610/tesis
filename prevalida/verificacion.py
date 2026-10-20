"""Verificación con el emisor (QR o código) y validación de firma electrónica avanzada.

- QR: se decodifica el código y se consulta al emisor. En el prototipo, el emisor
  es un registro simulado; en producción, la consulta va por la red de
  interoperabilidad del Estado o por el servicio de verificación del emisor.
- Firma electrónica avanzada (Ley 19.799): se valida la integridad del PDF y la
  cadena de certificación contra los certificados raíz de prestadores acreditados.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np


def leer_qr(imagen: bytes) -> str | None:
    arr = cv2.imdecode(np.frombuffer(imagen, np.uint8), cv2.IMREAD_GRAYSCALE)
    if arr is None:
        return None
    det = cv2.QRCodeDetector()
    for img in (arr, cv2.resize(arr, None, fx=1.5, fy=1.5), cv2.GaussianBlur(arr, (3, 3), 0)):
        txt, _, _ = det.detectAndDecode(img)
        if txt:
            return txt
    return None


class RegistroEmisor:
    """Emisor simulado (sustituible por un cliente de interoperabilidad real)."""

    def __init__(self, ruta: str | Path):
        self._r = json.loads(Path(ruta).read_text(encoding="utf-8"))

    def consultar(self, folio: str, codigo: str) -> dict | None:
        e = self._r.get(folio)
        if e and e["codigo"] == codigo:
            return {"titular": e["titular"], "fecha_emision": date.fromisoformat(e["fecha_emision"])}
        return None


def verificar_qr(imagen: bytes, emisor: RegistroEmisor) -> dict:
    txt = leer_qr(imagen)
    if not txt:
        return {"qr_leido": False, "existe": False}
    q = parse_qs(urlparse(txt).query)
    folio, codigo = q.get("folio", [""])[0], q.get("codigo", [""])[0]
    r = emisor.consultar(folio, codigo)
    if not r:
        return {"qr_leido": True, "existe": False, "folio": folio}
    return {"qr_leido": True, "existe": True, "folio": folio, **r}


def validar_fea(pdf: bytes, raices_acreditadas: list[bytes]) -> dict | None:
    """Devuelve None si el PDF no tiene firma; si la tiene, integridad y confianza."""
    from asn1crypto import pem, x509
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    logging.getLogger("pyhanko").setLevel(logging.CRITICAL)
    reader = PdfFileReader(io.BytesIO(pdf))
    if not reader.embedded_signatures:
        return None
    raices = []
    for r in raices_acreditadas:
        der = pem.unarmor(r)[2] if pem.detect(r) else r
        raices.append(x509.Certificate.load(der))
    vc = ValidationContext(trust_roots=raices, allow_fetching=False)
    st = validate_pdf_signature(reader.embedded_signatures[0], vc)
    return {
        "integra": bool(st.intact and st.valid),
        "confiable": bool(st.trusted),
        "firmante": st.signing_cert.subject.human_friendly if st.signing_cert else "",
        "cubre_todo": st.coverage.name == "ENTIRE_FILE" if st.coverage else False,
    }
