"""Detecciones por la razón correcta.

Un problema introducido cuenta como detectado por la razón correcta solo si el sistema emitió
el código esperado Y la evidencia que extrajo era la verdadera:

- nombre distinto o casi igual (pasaporte, certificado, liquidación): el nombre leído coincide
  con el de la verdad (EXACTO o SUBCONJUNTO; en la MRZ se admite el truncamiento);
- documento antiguo (certificado, liquidación): la fecha interpretada es la de la verdad;
- firmante distinto del empleador: el RUT del empleador leído es el de la verdad.

Los demás códigos dependen de la presencia o ausencia de un elemento (apostilla, firma), de
los dígitos de control de la MRZ o de la respuesta del emisor, y se cuentan como correctos.

Re-ejecuta la prevalidación con el código de CODE_DIR (por ejemplo, una copia de trabajo en la
etiqueta `congelado-evaluacion`) y la caché de OCR de la evaluación, sin volver a leer imágenes.

Uso: CODE_DIR=. CORPUS_DIR=corpus_ADV2 OUT_DIR=resultados_ADV2 python scripts/razon_correcta.py
Escribe OUT_DIR/razon_correcta.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

CODE = Path(os.environ.get("CODE_DIR", Path(__file__).resolve().parent.parent)).resolve()
CORPUS = Path(os.environ["CORPUS_DIR"]).resolve()
OUT = Path(os.environ["OUT_DIR"]).resolve()
sys.path.insert(0, str(CODE))

from prevalida import extraccion as ex  # noqa: E402
from prevalida.pipeline import Prevalidador  # noqa: E402
from prevalida.reglas import Contexto, MotorReglas, cargar_config  # noqa: E402
from prevalida.verificacion import RegistroEmisor, normalizar_rut  # noqa: E402


class SoloCache:
    """Motor OCR que responde solo desde la caché de la evaluación (mismas claves que evaluar.py)."""
    nombre = "tesseract"

    def __init__(self, ruta: Path, modelo_mrz: str = "mrz"):
        self.c = pickle.loads(ruta.read_bytes())
        self.modelo_mrz = modelo_mrz

    def leer(self, img, idioma):
        return self.c[hashlib.sha256(img).hexdigest() + idioma]

    def leer_mrz(self, img):
        return self.c[hashlib.sha256(img).hexdigest() + "mrz:" + self.modelo_mrz]


def valor(campos: dict, k: str):
    v = campos.get(k)
    return v.get("valor") if isinstance(v, dict) else v


def main():
    meta = json.loads((CORPUS / "verdad.json").read_text(encoding="utf-8"))
    fp = date.fromisoformat(meta["fecha_presentacion"])
    prev = Prevalidador(SoloCache(OUT / "cache_ocr.pkl"), MotorReglas(cargar_config(CODE / "config" / "reglas.yaml")),
                        RegistroEmisor(CORPUS / "emisor_simulado.json"),
                        [(CORPUS / "certs" / "raiz_acreditada.pem").read_bytes()])
    # Mismos documentos que la evaluación: los de metricas.json (prueba o corpus completo).
    evaluados = {x["id"] for x in json.loads((OUT / "metricas.json").read_text(encoding="utf-8"))["detalle"]}
    por = defaultdict(Counter)
    incorrectas = []
    for d in meta["documentos"]:
        if d["id"] not in evaluados:
            continue
        ctx = Contexto(fp, d["ctx"]["nombre_declarado"], d["ctx"].get("numero_pasaporte_declarado", ""))
        img = (CORPUS / d["imagen"]).read_bytes()
        pdf = (CORPUS / d["pdf"]).read_bytes() if d.get("pdf") else None
        r = prev.procesar(d["id"], d["tipo"], d["idioma"], img, ctx, pdf, d["pais"])
        prod = {h.codigo for h in r.hallazgos}
        v = d["verdad"]
        for c in d["esperados"]:
            k = f"{d['tipo']}|{c}"
            por[k]["n"] += 1
            if c not in prod:
                continue
            por[k]["detectados"] += 1
            ok = True
            if c in ("NOMBRE_NO_COINCIDE", "NOMBRE_CASI_COINCIDE") and d["tipo"] != "certificado_publico_cl":
                if d["tipo"] == "pasaporte":
                    leido = f'{r.campos.get("apellidos", "")} {r.campos.get("nombres", "")}'
                    ok = ex.comparar_nombres(leido, f'{v["apellidos"]} {v["nombres"]}',
                                             ultimo_truncado_a=True) in ("EXACTO", "SUBCONJUNTO")
                else:
                    ok = ex.comparar_nombres(valor(r.campos, "nombre"), v.get("nombre")) in ("EXACTO", "SUBCONJUNTO")
            elif c == "DOCUMENTO_ANTIGUO" and d["tipo"] != "certificado_publico_cl":
                ok = ex.parsear_fecha(valor(r.campos, "fecha_emision")) == date.fromisoformat(v["fecha_emision"])
            elif c == "FIRMANTE_NO_COINCIDE":
                ok = normalizar_rut(valor(r.campos, "rut_empleador") or "") == normalizar_rut(v["rut_empleador"])
            if ok:
                por[k]["razon_correcta"] += 1
            else:
                incorrectas.append({"id": d["id"], "codigo": c})
    res = {"codigo": str(CODE), "corpus": CORPUS.name,
           "esperados": sum(x["n"] for x in por.values()),
           "detectados": sum(x["detectados"] for x in por.values()),
           "razon_correcta": sum(x["razon_correcta"] for x in por.values()),
           "por_tipo_y_codigo": {k: dict(v) for k, v in sorted(por.items())},
           "detecciones_con_evidencia_incorrecta": incorrectas}
    (OUT / "razon_correcta.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("corpus", "esperados", "detectados", "razon_correcta")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
