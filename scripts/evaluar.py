"""Evaluación del prototipo sobre el corpus sintético (demostración DSR).

1. Ejecuta el OCR una vez por documento (resultados en caché).
2. Divide el corpus en calibración y prueba (50/50, estratificado por tipo e idioma).
3. Calibra el umbral de confianza por idioma con la muestra de calibración.
4. Mide en la muestra de prueba: precisión de lo aceptado (con intervalos de
   Clopper-Pearson), cobertura, falsas alertas, detección de hallazgos,
   derivaciones a revisión humana, validez de la MRZ, firma, QR y latencia.
"""
from __future__ import annotations

import hashlib
import json
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

import os
CORPUS = Path(os.environ.get("CORPUS_DIR", BASE / "corpus"))
OUT = Path(os.environ.get("OUT_DIR", BASE / "resultados"))
OUT.mkdir(exist_ok=True)
SEED = 7


def cp(k: int, n: int, alfa: float = 0.05) -> tuple[float, float]:
    """Intervalo exacto de Clopper-Pearson (bilateral, 95 %)."""
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else beta.ppf(alfa / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(1 - alfa / 2, k + 1, n - k)
    return float(lo), float(hi)


def cp_inferior(k: int, n: int, alfa: float = 0.05) -> float:
    """Límite inferior unilateral (95 %) de Clopper-Pearson."""
    return 0.0 if k == 0 or n == 0 else float(beta.ppf(alfa, k, n - k + 1))


class MotorEnCache:
    """Envuelve el motor real y guarda cada lectura para no repetir el OCR."""

    def __init__(self, motor, ruta: Path):
        self.m, self.ruta, self.nombre = motor, ruta, motor.nombre
        self.c = pickle.loads(ruta.read_bytes()) if ruta.exists() else {}

    def _k(self, img, sufijo):
        return hashlib.sha256(img).hexdigest() + sufijo

    def leer(self, img, idioma):
        k = self._k(img, idioma)
        if k not in self.c:
            self.c[k] = self.m.leer(img, idioma)
        return self.c[k]

    def leer_mrz(self, img):
        k = self._k(img, "mrz")
        if k not in self.c:
            self.c[k] = self.m.leer_mrz(img)
        return self.c[k]

    def guardar(self):
        self.ruta.write_bytes(pickle.dumps(self.c))


def norm_digitos(s):
    return re.sub(r"\D", "", s or "")


def correcto(campo: str, valor, verdad: dict) -> bool:
    if valor is None:
        return False
    if campo == "nombre":
        return ex.normalizar_nombre(valor) == ex.normalizar_nombre(verdad["nombre"])
    if campo == "fecha_emision":
        return ex.parsear_fecha(valor) == date.fromisoformat(verdad["fecha_emision"])
    if campo in ("documento", "folio", "liquido"):
        return norm_digitos(valor) == norm_digitos(verdad[campo])
    if campo == "rut_empleador":
        return re.sub(r"[^0-9K]", "", valor.upper()) == re.sub(r"[^0-9K]", "", verdad[campo].upper())
    if campo == "periodo":
        return re.sub(r"\s", "", valor) == verdad[campo]
    return False


def dividir(docs):
    rng = random.Random(SEED)
    grupos = defaultdict(list)
    for d in docs:
        grupos[(d["tipo"], d["idioma"])].append(d)
    cal, pru = [], []
    for g in grupos.values():
        g = sorted(g, key=lambda d: d["id"]); rng.shuffle(g)
        cal += g[: len(g) // 2]; pru += g[len(g) // 2:]
    return cal, pru


def campos_ocr(docs, motor):
    """Pares (idioma, campo, confianza, correcto) de los documentos procesados con OCR."""
    filas = []
    for d in docs:
        if d["tipo"] not in ("antecedentes_extranjero", "liquidacion") or d["idioma"] == "ht":
            continue
        img = (CORPUS / d["imagen"]).read_bytes()
        o = motor.leer(img, d["idioma"])
        tipo = "antecedentes" if d["tipo"] == "antecedentes_extranjero" else "liquidacion"
        for k, c in ex.extraer_etiquetados(o, tipo).items():
            filas.append({"id": d["id"], "idioma": d["idioma"], "campo": k, "conf": c.confianza,
                          "correcto": correcto(k, c.valor, d["verdad"]), "degradacion": d["degradacion"]})
    return filas


def calibrar(filas, objetivo=0.99):
    """Umbral más bajo cuya precisión empírica de lo aceptado alcanza el objetivo."""
    umbrales, curvas = {}, {}
    for idioma in sorted({f["idioma"] for f in filas}):
        fs = [f for f in filas if f["idioma"] == idioma]
        curva = []
        elegido = 1.01
        for t in [x / 100 for x in range(0, 100)]:
            acc = [f for f in fs if f["conf"] >= t]
            prec = sum(f["correcto"] for f in acc) / len(acc) if acc else float("nan")
            curva.append((t, prec, len(acc) / len(fs)))
            if acc and prec >= objetivo and elegido > 1:
                elegido = t
        umbrales[idioma] = elegido
        curvas[idioma] = curva
    return umbrales, curvas


def metricas_campos(filas, umbrales):
    out = {}
    for idioma in sorted({f["idioma"] for f in filas}):
        fs = [f for f in filas if f["idioma"] == idioma]
        acc = [f for f in fs if f["conf"] >= umbrales[idioma]]
        k = sum(f["correcto"] for f in acc)
        out[idioma] = {"campos": len(fs), "aceptados": len(acc), "correctos_aceptados": k,
                       "precision": k / len(acc) if acc else None, "ic95": cp(k, len(acc)),
                       "lim_inf_unilateral": cp_inferior(k, len(acc)),
                       "cobertura": len(acc) / len(fs) if fs else None,
                       "exactitud_global": sum(f["correcto"] for f in fs) / len(fs)}
    return out


def main():
    meta = json.loads((CORPUS / "verdad.json").read_text(encoding="utf-8"))
    fp = date.fromisoformat(meta["fecha_presentacion"])
    docs = meta["documentos"]
    motor = MotorEnCache(TesseractOCR(str(BASE / "tessdata")), OUT / "cache_ocr.pkl")
    cfg = cargar_config(BASE / "config" / "reglas.yaml")
    raices = [(CORPUS / "certs" / "raiz_acreditada.pem").read_bytes()]
    emisor = RegistroEmisor(CORPUS / "emisor_simulado.json")

    cal, pru = dividir(docs)
    # 1) Calibración del umbral por idioma (solo muestra de calibración)
    filas_cal = campos_ocr(cal, motor)
    umbrales, curvas = calibrar(filas_cal)
    motor.guardar()
    # 2) Campos en la muestra de prueba
    filas_pru = campos_ocr(pru, motor)
    m_campos = metricas_campos(filas_pru, umbrales)
    m_campos_defecto = metricas_campos(filas_pru, {k: cfg["umbrales"]["defecto"] for k in umbrales})
    exact_deg = {}
    for deg in ("limpio", "escaner", "celular", "baja_res"):
        fs = [f for f in filas_pru if f["degradacion"] == deg]
        exact_deg[deg] = sum(f["correcto"] for f in fs) / len(fs)
    motor.guardar()

    # 3) Prevalidación completa de cada documento de prueba
    reglas = MotorReglas(cfg, {(c, i): t for i, t in umbrales.items() for c in ("nombre", "fecha_emision")})
    bit = Bitacora()
    prev = Prevalidador(motor, reglas, emisor, raices, bit)
    det = defaultdict(Counter)
    por_idioma = defaultdict(Counter)
    tiempos, mrz_deg, qr_deg, fea = [], defaultdict(Counter), defaultdict(Counter), []
    detalle = []
    for d in pru:
        ctx = Contexto(fp, d["ctx"]["nombre_declarado"], d["ctx"].get("numero_pasaporte_declarado", ""))
        img = (CORPUS / d["imagen"]).read_bytes()
        pdf = (CORPUS / d["pdf"]).read_bytes() if d.get("pdf") else None
        r = prev.procesar(d["id"], d["tipo"], d["idioma"], img, ctx, pdf)
        prod = {h.codigo for h in r.hallazgos}
        alertas = {h.codigo for h in r.hallazgos if h.tipo == "ALERTA"}
        deriv = {h.codigo for h in r.hallazgos if h.tipo == "REVISION_HUMANA"}
        esp = set(d["esperados"])
        for c in esp | prod:
            det[c]["vp" if c in esp and c in prod else ("fn" if c in esp else "fp")] += 1
        # Problemas esperados no detectados en documentos marcados como prevalidados = omisión silenciosa
        omision_silenciosa = bool(esp - prod) and r.estado == "PREVALIDADO"
        derivacion_incierta = bool(deriv - esp)
        g = d["idioma"] if d["tipo"] != "certificado_publico_cl" else "es (emisor)"
        por_idioma[g]["docs"] += 1
        por_idioma[g]["falsa_alerta"] += bool(alertas - esp)
        por_idioma[g]["derivacion_incertidumbre"] += derivacion_incierta
        por_idioma[g]["omision_silenciosa"] += omision_silenciosa
        por_idioma[g]["prevalidado_sin_derivar"] += r.estado != "REVISION_HUMANA"
        if d["tipo"] == "pasaporte":
            ok = r.campos.get("controles") and all(r.campos["controles"].values())
            mrz_deg[d["degradacion"]]["n"] += 1
            mrz_deg[d["degradacion"]]["valida"] += bool(ok)
            if ok:
                v = d["verdad"]
                exacto = (r.campos["numero"] == v["numero"] and r.campos["vencimiento"] == v["vencimiento"]
                          and ex.normalizar_nombre(r.campos["apellidos"] + " " + r.campos["nombres"])
                          == ex.normalizar_nombre(v["apellidos"] + " " + v["nombres"]))
                mrz_deg[d["degradacion"]]["valida_exacta"] += exacto
        if d["tipo"] == "certificado_publico_cl":
            qr_deg[d["degradacion"]]["n"] += 1
            qr_deg[d["degradacion"]]["leido"] += r.campos.get("qr_leido") == "True"
        if d["tipo"] == "liquidacion":
            fea.append({"id": d["id"], "variante": int(d["id"][-3:]) % 4, "firma": r.campos.get("firma"),
                        "esperados": sorted(esp & {"FIRMA_INVALIDA", "FIRMANTE_NO_ACREDITADO", "SIN_FEA"}),
                        "producidos": sorted(prod & {"FIRMA_INVALIDA", "FIRMANTE_NO_ACREDITADO", "SIN_FEA"})})
        if r.via not in ("emisor", "directo_humano"):
            tiempos.append(r.segundos)
        detalle.append({"id": d["id"], "tipo": d["tipo"], "idioma": d["idioma"], "degradacion": d["degradacion"],
                        "estado": r.estado, "esperados": sorted(esp), "producidos": sorted(prod)})
    motor.guardar()

    # Latencia real de OCR (primera ejecución, desde la caché)
    ocr_t = [v.segundos for v in motor.c.values()]
    # 4) Integridad de la bitácora y detección de alteraciones
    integra = bit.verificar()
    bit.db.execute("UPDATE eventos SET datos = '{\"estado\": \"PREVALIDADO\"}' WHERE id = 3"); bit.db.commit()
    alteracion_detectada = not bit.verificar()

    res = {
        "corpus": {"total": len(docs), "calibracion": len(cal), "prueba": len(pru),
                   "por_tipo": Counter(d["tipo"] for d in docs), "fecha_presentacion": meta["fecha_presentacion"]},
        "umbrales_calibrados": umbrales,
        "campos_prueba_calibrado": m_campos, "campos_prueba_umbral_defecto_0_80": m_campos_defecto,
        "exactitud_campos_por_degradacion": exact_deg,
        "deteccion_por_codigo": {k: dict(v) for k, v in sorted(det.items())},
        "por_idioma": {k: dict(v) for k, v in por_idioma.items()},
        "mrz_por_degradacion": {k: dict(v) for k, v in mrz_deg.items()},
        "qr_por_degradacion": {k: dict(v) for k, v in qr_deg.items()},
        "fea": fea,
        "latencia_ocr_s": {"n": len(ocr_t), "mediana": statistics.median(ocr_t),
                           "p95": sorted(ocr_t)[int(0.95 * (len(ocr_t) - 1))], "max": max(ocr_t)},
        "latencia_prevalidacion_s": {"mediana": statistics.median(tiempos),
                                     "p95": sorted(tiempos)[int(0.95 * (len(tiempos) - 1))]},
        "bitacora": {"integra": integra, "alteracion_detectada": alteracion_detectada},
        "detalle": detalle,
    }
    (OUT / "metricas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "curvas_umbral.json").write_text(json.dumps(curvas), encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, len(curvas), figsize=(9, 3.2), sharey=True)
    for a, (idioma, c) in zip(ax, curvas.items()):
        t = [x[0] for x in c]
        a.plot(t, [x[1] for x in c], label="Precisión de lo aceptado", color="#1f4e79")
        a.plot(t, [x[2] for x in c], label="Cobertura", color="#c55a11", linestyle="--")
        a.axvline(umbrales[idioma], color="gray", linestyle=":", linewidth=1)
        a.axhline(0.99, color="gray", linewidth=0.5)
        a.set_title({"es": "Español", "fr": "Francés"}.get(idioma, idioma))
        a.set_xlabel("Umbral de confianza"); a.set_ylim(0, 1.02)
    ax[0].set_ylabel("Proporción"); ax[0].legend(loc="lower left", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "curva_umbral.pdf"); fig.savefig(OUT / "curva_umbral.png", dpi=150)
    print(json.dumps({k: v for k, v in res.items() if k != "detalle"}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
