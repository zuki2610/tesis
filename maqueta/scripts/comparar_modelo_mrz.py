"""Compara el modelo genérico `eng` con el modelo `mrz` (OCR-B) en la lectura de la MRZ.

Usa los pasaportes de la mitad de calibración del corpus de desarrollo (nunca la de
prueba), que fue donde se tomó la decisión de cambiar de modelo en la iteración 4.

Uso: CORPUS_DIR=corpus_D python scripts/comparar_modelo_mrz.py
Escribe resultados_modelo_mrz.json.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "scripts"))
from evaluar import dividir  # noqa: E402
from prevalida import extraccion as ex  # noqa: E402
from prevalida.ocr import TesseractOCR  # noqa: E402

CORPUS = Path(os.environ.get("CORPUS_DIR", BASE / "corpus_D"))


def main():
    meta = json.loads((CORPUS / "verdad.json").read_text(encoding="utf-8"))
    cal, _ = dividir(meta["documentos"], meta["semilla"])
    pas = [d for d in cal if d["tipo"] == "pasaporte"]
    out = {"corpus": CORPUS.name, "muestra": "calibracion", "pasaportes": len(pas)}
    for modelo in ("eng", "mrz"):
        m = TesseractOCR(str(BASE / "tessdata"), modelo_mrz=modelo)
        validas, exactas, por_pais = 0, 0, Counter()
        for d in pas:
            r, _ = ex.extraer_mrz(m.leer_mrz((CORPUS / d["imagen"]).read_bytes()))
            ok = bool(r and r.valida)
            validas += ok; por_pais[d["pais"]] += ok
            v = d["verdad"]
            exactas += ok and r.numero == v["numero"] and ex.normalizar_nombre(
                r.apellidos + " " + r.nombres) == ex.normalizar_nombre(v["apellidos"] + " " + v["nombres"])
        out[modelo] = {"validas": validas, "exactas": exactas, "por_pais": dict(sorted(por_pais.items()))}
        print(modelo, out[modelo], flush=True)
    (BASE / "resultados_modelo_mrz.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
