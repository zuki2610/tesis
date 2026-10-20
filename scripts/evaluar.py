"""Evaluación del prototipo sobre un corpus sintético (versión 2).

1. Divide el corpus en calibración y prueba (50/50, estratificado por tipo e idioma,
   con una semilla derivada de la del corpus).
2. Calibra el umbral de confianza por idioma (muestra de calibración) y lo compara con
   el umbral por defecto (0,80).
3. Mide en la muestra de prueba, solo sobre los campos que usan las reglas:
   exactitud estricta (texto idéntico salvo mayúsculas y espacios) y funcional (forma
   normalizada que usan las reglas), precisión de lo aceptado con intervalos de
   Clopper-Pearson y bootstrap por documento, y cobertura.
4. Ejecuta la prevalidación completa y mide: detección por tipo de hallazgo, omisiones,
   alertas injustificadas (por documento y por alerta), derivaciones por incertidumbre,
   desglose por país e idioma, MRZ, QR, firma, latencia y bitácora.

Uso: CORPUS_DIR=corpus_D OUT_DIR=resultados_D python scripts/evaluar.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from scipy.stats import beta

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from prevalida import extraccion as ex  # noqa: E402
from prevalida.bitacora import Bitacora  # noqa: E402
from prevalida.ocr import TesseractOCR  # noqa: E402
from prevalida.pipeline import Prevalidador  # noqa: E402
from prevalida.reglas import Contexto, MotorReglas, cargar_config  # noqa: E402
from prevalida.verificacion import RegistroEmisor  # noqa: E402

CORPUS = Path(os.environ.get("CORPUS_DIR", BASE / "corpus"))
OUT = Path(os.environ.get("OUT_DIR", BASE / "resultados"))
OUT.mkdir(parents=True, exist_ok=True)


def cp(k: int, n: int, alfa: float = 0.05) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else beta.ppf(alfa / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(1 - alfa / 2, k + 1, n - k)
    return float(lo), float(hi)


def cp_inferior(k: int, n: int, alfa: float = 0.05) -> float:
    return 0.0 if k == 0 or n == 0 else float(beta.ppf(alfa, k, n - k + 1))


def cp_superior(k: int, n: int, alfa: float = 0.05) -> float:
    return 1.0 if n == 0 or k == n else float(beta.ppf(1 - alfa, k + 1, n - k))


class MotorEnCache:
    """Guarda cada lectura para no repetir el OCR. `ultimo_segundos` conserva el tiempo de
    OCR de la lectura original, para medir la latencia real aunque se lea de la caché."""

    def __init__(self, motor, ruta: Path):
        self.m, self.ruta, self.nombre = motor, ruta, motor.nombre
        self.c = pickle.loads(ruta.read_bytes()) if ruta.exists() else {}
        self.ultimo_segundos = 0.0

    def _k(self, img, sufijo):
        return hashlib.sha256(img).hexdigest() + sufijo

    def leer(self, img, idioma):
        k = self._k(img, idioma)
        if k not in self.c:
            self.c[k] = self.m.leer(img, idioma)
        self.ultimo_segundos = self.c[k].segundos
        return self.c[k]

    def leer_mrz(self, img):
        k = self._k(img, "mrz:" + self.m.modelo_mrz)
        if k not in self.c:
            self.c[k] = self.m.leer_mrz(img)
        self.ultimo_segundos = self.c[k].segundos
        return self.c[k]

    def guardar(self):
        self.ruta.write_bytes(pickle.dumps(self.c))


def _estricto(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def correcto(campo: str, valor, verdad: dict, modo: str) -> bool:
    if valor is None:
        return False
    if campo == "nombre":
        if modo == "estricto":
            return _estricto(valor) == _estricto(verdad["nombre"])
        return ex.normalizar_nombre(valor) == ex.normalizar_nombre(verdad["nombre"])
    if campo == "fecha_emision":
        if modo == "estricto":
            return ex.parsear_fecha(valor) == date.fromisoformat(verdad["fecha_emision"])
        return ex.parsear_fecha(valor) == date.fromisoformat(verdad["fecha_emision"])
    if campo == "rut_empleador":
        return re.sub(r"[^0-9K]", "", valor.upper()) == re.sub(r"[^0-9K]", "", verdad[campo].upper())
    return False


def dividir(docs, semilla):
    rng = random.Random(semilla)
    grupos = defaultdict(list)
    for d in docs:
        grupos[(d["tipo"], d["idioma"])].append(d)
    cal, pru = [], []
    for g in grupos.values():
        g = sorted(g, key=lambda d: d["id"]); rng.shuffle(g)
        cal += g[: len(g) // 2]; pru += g[len(g) // 2:]
    return cal, pru


def campos_ocr(docs, motor):
    """Campos usados por las reglas, leídos con OCR desde la imagen."""
    filas = []
    for d in docs:
        if d["tipo"] not in ("antecedentes_extranjero", "liquidacion") or not d["verdad"]:
            continue
        o = motor.leer((CORPUS / d["imagen"]).read_bytes(), d["idioma"])
        tipo = "antecedentes" if d["tipo"] == "antecedentes_extranjero" else "liquidacion"
        campos = ex.extraer_etiquetados(o, tipo)
        for k in ex.CAMPOS_USADOS[tipo]:
            c = campos[k]
            filas.append({"id": d["id"], "idioma": d["idioma"], "campo": k, "conf": c.confianza,
                          "encontrado": c.valor is not None,
                          "estricto": correcto(k, c.valor, d["verdad"], "estricto"),
                          "funcional": correcto(k, c.valor, d["verdad"], "funcional"),
                          "degradacion": d["degradacion"], "pais": d["pais"]})
    return filas


def calibrar(filas, objetivo=0.99, metrica="estricto"):
    umbrales, curvas = {}, {}
    for idioma in sorted({f["idioma"] for f in filas}):
        fs = [f for f in filas if f["idioma"] == idioma]
        curva, elegido = [], None
        for t in [x / 100 for x in range(0, 101)]:
            acc = [f for f in fs if f["conf"] >= t and f["encontrado"]]
            prec = sum(f[metrica] for f in acc) / len(acc) if acc else float("nan")
            curva.append((t, prec, len(acc) / len(fs)))
            if acc and prec >= objetivo and elegido is None:
                elegido = t
        umbrales[idioma] = elegido if elegido is not None else 1.01
        curvas[idioma] = curva
    return umbrales, curvas


def bootstrap_precision(fs, reps=2000, semilla=1):
    """IC 95 % de la precisión de lo aceptado remuestreando documentos (no campos)."""
    por_doc = defaultdict(list)
    for f in fs:
        por_doc[f["id"]].append(f)
    ids = list(por_doc)
    if not ids:
        return (float("nan"), float("nan"))
    rng = random.Random(semilla)
    vals = []
    for _ in range(reps):
        m = [f for i in (rng.choice(ids) for _ in ids) for f in por_doc[i]]
        if m:
            vals.append(sum(f["estricto"] for f in m) / len(m))
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def metricas_campos(filas, umbrales):
    out = {}
    for idioma in sorted({f["idioma"] for f in filas}):
        fs = [f for f in filas if f["idioma"] == idioma]
        acc = [f for f in fs if f["encontrado"] and f["conf"] >= umbrales[idioma]]
        k = sum(f["estricto"] for f in acc)
        out[idioma] = {"campos": len(fs), "documentos": len({f["id"] for f in fs}), "aceptados": len(acc),
                       "correctos_aceptados_estricto": k,
                       "correctos_aceptados_funcional": sum(f["funcional"] for f in acc),
                       "precision": k / len(acc) if acc else None, "ic95_cp": cp(k, len(acc)),
                       "lim_inf_unilateral": cp_inferior(k, len(acc)),
                       "ic95_bootstrap_documentos": bootstrap_precision(acc),
                       "cobertura": len(acc) / len(fs) if fs else None,
                       "exactitud_estricta_global": sum(f["estricto"] for f in fs) / len(fs),
                       "exactitud_funcional_global": sum(f["funcional"] for f in fs) / len(fs),
                       "errores_aceptados": [{"id": f["id"], "campo": f["campo"]} for f in acc if not f["estricto"]]}
    return out


def main():
    meta = json.loads((CORPUS / "verdad.json").read_text(encoding="utf-8"))
    fp = date.fromisoformat(meta["fecha_presentacion"])
    docs = meta["documentos"]
    motor = MotorEnCache(TesseractOCR(str(BASE / "tessdata")), OUT / "cache_ocr.pkl")
    cfg = cargar_config(BASE / "config" / "reglas.yaml")
    raices = [(CORPUS / "certs" / "raiz_acreditada.pem").read_bytes()]
    emisor = RegistroEmisor(CORPUS / "emisor_simulado.json")

    cal, pru = dividir(docs, meta["semilla"])
    filas_cal = campos_ocr(cal, motor); motor.guardar()
    umbrales, curvas = calibrar(filas_cal)
    filas_pru = campos_ocr(pru, motor); motor.guardar()
    defecto = {k: cfg["umbrales"]["defecto"] for k in umbrales}
    m_cal = metricas_campos(filas_pru, umbrales)
    m_def = metricas_campos(filas_pru, defecto)
    exact_deg = {deg: (lambda fs: sum(f["estricto"] for f in fs) / len(fs) if fs else None)(
        [f for f in filas_pru if f["degradacion"] == deg]) for deg in ("limpio", "escaner", "celular", "baja_res")}

    # Prevalidación completa con el umbral por defecto (configuración entregada).
    bit = Bitacora()
    prev = Prevalidador(motor, MotorReglas(cfg), emisor, raices, bit)
    det = defaultdict(Counter)
    grupos = defaultdict(Counter)
    mrz = defaultdict(Counter); qr = Counter(); firma = defaultdict(Counter)
    tiempos, detalle = [], []
    alertas_total = alertas_injust = 0
    for d in pru:
        ctx = Contexto(fp, d["ctx"]["nombre_declarado"], d["ctx"].get("numero_pasaporte_declarado", ""))
        img = (CORPUS / d["imagen"]).read_bytes()
        pdf = (CORPUS / d["pdf"]).read_bytes() if d.get("pdf") else None
        motor.ultimo_segundos = 0.0
        r = prev.procesar(d["id"], d["tipo"], d["idioma"], img, ctx, pdf, d["pais"])
        prod = {h.codigo for h in r.hallazgos}
        alertas = {h.codigo for h in r.hallazgos if h.tipo == "ALERTA"}
        deriv = {h.codigo for h in r.hallazgos if h.tipo == "REVISION_HUMANA"}
        esp = set(d["esperados"])
        for c in esp | prod:
            det[c]["vp" if c in esp and c in prod else ("fn" if c in esp else "fp")] += 1
        alertas_total += len(alertas); alertas_injust += len(alertas - esp)
        g = (d["tipo"], d["pais"])
        grupos[g]["docs"] += 1
        grupos[g]["con_alerta_injustificada"] += bool(alertas - esp)
        grupos[g]["con_derivacion_no_esperada"] += bool(deriv - esp)
        grupos[g]["con_omision"] += bool(esp - prod)
        grupos[g]["omision_silenciosa"] += bool(esp - prod) and r.estado == "PREVALIDADO"
        grupos[g]["omision_con_derivacion"] += bool(esp - prod) and r.estado == "REVISION_HUMANA"
        grupos[g]["omision_con_alertas"] += bool(esp - prod) and r.estado == "CON_ALERTAS"
        grupos[g]["prevalidado"] += r.estado == "PREVALIDADO"
        if d["tipo"] == "pasaporte":
            ok = bool(r.campos.get("controles")) and all(r.campos["controles"].values())
            mrz[d["pais"]]["n"] += 1; mrz[d["pais"]]["valida"] += ok
            mrz["deg_" + d["degradacion"]]["n"] += 1; mrz["deg_" + d["degradacion"]]["valida"] += ok
            if ok:
                v = d["verdad"]
                mrz[d["pais"]]["exacta"] += (r.campos["numero"] == v["numero"] and r.campos["vencimiento"] == v["vencimiento"]
                                             and ex.normalizar_nombre(r.campos["apellidos"] + " " + r.campos["nombres"])
                                             == ex.normalizar_nombre(v["apellidos"] + " " + v["nombres"]))
        if d["tipo"] == "certificado_publico_cl":
            qr["n"] += 1; qr["leido"] += r.campos.get("qr_leido") == "True"
        if d["tipo"] == "liquidacion":
            v = d["variante_firma"]
            firma[v]["n"] += 1
            firma[v]["correcta"] += (esp & {"FIRMA_INVALIDA", "MODIFICADO_TRAS_FIRMA", "FIRMANTE_NO_ACREDITADO",
                                            "FIRMANTE_NO_COINCIDE", "SIN_FEA"}) == (prod & {
                "FIRMA_INVALIDA", "MODIFICADO_TRAS_FIRMA", "FIRMANTE_NO_ACREDITADO", "FIRMANTE_NO_COINCIDE", "SIN_FEA"})
            firma[v]["via_" + r.via] += 1
        if r.via in ("ocr", "ocr_mrz", "firma_y_ocr"):
            tiempos.append(r.segundos + motor.ultimo_segundos)  # reglas + OCR original
        detalle.append({"id": d["id"], "tipo": d["tipo"], "pais": d["pais"], "idioma": d["idioma"],
                        "degradacion": d["degradacion"], "via": r.via, "estado": r.estado,
                        "esperados": sorted(esp), "producidos": sorted(prod)})
    motor.guardar()

    ancla = bit.ancla()
    integra = bit.verificar(ancla)
    bit.db.execute("DELETE FROM eventos WHERE id = (SELECT MAX(id) FROM eventos)"); bit.db.commit()
    truncamiento_detectado = not bit.verificar(ancla)

    n_docs = len(pru)
    docs_alerta_injust = sum(v["con_alerta_injustificada"] for v in grupos.values())
    res = {
        "motor": {"tesseract": __import__("pytesseract").get_tesseract_version().public, "modelo_mrz": motor.m.modelo_mrz},
        "corpus": {"total": len(docs), "calibracion": len(cal), "prueba": n_docs, "semilla": meta["semilla"],
                   "generador": meta.get("generador", "v1"), "por_tipo": Counter(d["tipo"] for d in docs)},
        "umbrales_calibrados": umbrales, "umbral_defecto": cfg["umbrales"]["defecto"],
        "campos_umbral_calibrado": m_cal, "campos_umbral_defecto": m_def,
        "exactitud_estricta_por_degradacion": exact_deg,
        "deteccion_por_codigo": {k: dict(v) for k, v in sorted(det.items())},
        "totales": {
            "esperados": sum(v.get("vp", 0) + v.get("fn", 0) for v in det.values()),
            "detectados": sum(v.get("vp", 0) for v in det.values()),
            "omitidos": sum(v.get("fn", 0) for v in det.values()),
            "hallazgos_no_esperados": sum(v.get("fp", 0) for v in det.values()),
            "documentos": n_docs,
            "documentos_con_omision": sum(v["con_omision"] for v in grupos.values()),
            "omisiones_silenciosas": sum(v["omision_silenciosa"] for v in grupos.values()),
            "omisiones_con_derivacion": sum(v["omision_con_derivacion"] for v in grupos.values()),
            "omisiones_con_alertas": sum(v["omision_con_alertas"] for v in grupos.values()),
            "documentos_derivados": sum(1 for x in detalle if x["estado"] == "REVISION_HUMANA"),
            "documentos_con_alerta_injustificada": docs_alerta_injust,
            "ic95_doc_alerta_injustificada": cp(docs_alerta_injust, n_docs),
            "alertas": alertas_total, "alertas_injustificadas": alertas_injust,
            "documentos_con_derivacion_no_esperada": sum(v["con_derivacion_no_esperada"] for v in grupos.values()),
            "prevalidados": sum(v["prevalidado"] for v in grupos.values()),
        },
        "por_tipo_y_pais": {f"{k[0]}|{k[1]}": dict(v) for k, v in sorted(grupos.items())},
        "mrz": {k: dict(v) for k, v in sorted(mrz.items())},
        "qr": dict(qr), "firma_por_variante": {k: dict(v) for k, v in sorted(firma.items())},
        "latencia_documentos_ocr_prueba_s": {"n": len(tiempos), "mediana": statistics.median(tiempos),
                                             "p95": sorted(tiempos)[int(0.95 * (len(tiempos) - 1))]},
        "bitacora": {"integra_con_ancla": integra, "truncamiento_detectado": truncamiento_detectado},
        "detalle": detalle,
    }
    (OUT / "metricas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "curvas_umbral.json").write_text(json.dumps(curvas), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "detalle"}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
