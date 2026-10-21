"""Genera el resumen de resultados, las figuras y la tabla por condición adversarial de la
tesis a partir de los metricas.json y de los verdad.json de los corpus.

Uso: python scripts/figuras.py
Escribe resultados_resumen.json, figuras/*.pdf|png, figuras/tabla_condiciones.tex y
figuras/tabla_deteccion.tex.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
EVAL = {"D (it. 4)": "resultados_D_it4", "D (it. 5)": "resultados_D5",
        "ADV (it. 4)": "resultados_ADV_it4", "ADV2 (it. 5)": "resultados_ADV2"}
CORPUS = {"ADV (it. 4)": "corpus_ADV", "ADV2 (it. 5)": "corpus_ADV2"}
ALERTAS = {"NOMBRE_NO_COINCIDE", "NUMERO_NO_COINCIDE", "PASAPORTE_VENCIDO", "DOCUMENTO_ANTIGUO", "SIN_APOSTILLA",
           "SIN_LEGALIZACION", "SIN_APOSTILLA_NI_LEGALIZACION", "FALTA_ANTECEDENTES_PAIS", "SIN_FEA", "FIRMA_INVALIDA",
           "MODIFICADO_TRAS_FIRMA", "FIRMANTE_NO_COINCIDE", "CODIGO_INEXISTENTE", "CODIGO_DE_OTRA_PERSONA"}
CONDICIONES = [  # (grupo, clave, descripción para la tabla)
    ("Pasaportes", "pas:(ninguna)", "Sin márgenes ni nombre truncado"),
    ("Pasaportes", "pas:con_margen", "Fotografiado con márgenes"),
    ("Pasaportes", "pas:nombre_truncado", "Nombre truncado en la MRZ"),
    ("Certificados de antecedentes", "ant:etiqueta_misma_linea", "Etiqueta y valor en la misma línea"),
    ("Certificados de antecedentes", "ant:etiqueta_linea_aparte", "Valor en la línea siguiente a la etiqueta"),
    ("Certificados de antecedentes", "ant:trampa_padre", "«Nombre del padre» antes del titular"),
    ("Certificados de antecedentes", "ant:titular_expedido", "Etiquetas «Titular» y «Expedido el»"),
    ("Certificados de antecedentes", "ant:lugar_y_fecha", "«Apellidos y nombres» y «Lugar y fecha»"),
    ("Certificados de antecedentes", "ant:nom_prenom_separados", "«Nom» y «Prénom(s)» separados"),
    ("Certificados de antecedentes", "ant:fait_a", "«Fait à \\ldots, le \\ldots»"),
    ("Certificados de antecedentes", "ant:criollo_declarado_fr", "Criollo haitiano declarado como francés"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:dd/mm/aaaa", "dd/mm/aaaa"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:aaaa/mm/dd", "aaaa/mm/dd"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:fr_textual", "Textual en francés («le 3 août 2026»)"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:coma", "Con coma («3 de agosto, 2026»)"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:mes_primero", "Mes antes del día («Agosto 3 de 2026»)"),
    ("Formato de fecha (antecedentes y liquidaciones)", "fecha:anio_2", "Año de dos dígitos (dd/mm/aa)"),
    ("Liquidaciones de sueldo", "liq:plantilla_conocida", "Plantilla conocida"),
    ("Liquidaciones de sueldo", "liq:plantilla_nueva", "Plantilla nueva (otras etiquetas)"),
    ("Certificados chilenos con QR", "cer:qr_110px", "QR de 110 px"),
    ("Certificados chilenos con QR", "cer:qr_140px", "QR de 140 px"),
    ("Certificados chilenos con QR", "cer:qr_200px", "QR de 200 px"),
]
PAISES = ["VEN", "PER", "COL", "BOL", "HTI"]
NOMBRE_PAIS = {"VEN": "Venezuela", "PER": "Perú", "COL": "Colombia", "BOL": "Bolivia", "HTI": "Haití"}


def cargar(d):
    return json.loads((BASE / d / "metricas.json").read_text(encoding="utf-8"))


DERIVACIONES = {"MRZ_NO_ENCONTRADA", "MRZ_ILEGIBLE", "VENCIDO_CON_EXCEPCION", "NUMERO_CASI_COINCIDE",
                "NOMBRE_CASI_COINCIDE", "DOCUMENTO_NO_RECONOCIDO", "NOMBRE_DUDOSO", "FECHA_EMISION_DUDOSO",
                "FECHA_NO_INTERPRETABLE", "FECHA_FUTURA", "FIRMANTE_NO_ACREDITADO", "RUT_NO_LEIDO", "QR_ILEGIBLE",
                "IDIOMA_NO_SOPORTADO"}
NO_SOPORTADO = {"IDIOMA_NO_SOPORTADO", "DOCUMENTO_NO_RECONOCIDO"}  # documentos en criollo


def cp(k, n, a=0.05):
    from scipy.stats import beta
    return (0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1)),
            1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k)))


def por_pais(r):
    """Por país: documentos, derivados, derivados por incertidumbre de lectura (derivación
    no esperada) y con alerta injustificada. Excluye los documentos en criollo, cuya
    derivación es el comportamiento esperado."""
    out = {}
    for p in PAISES:
        xs = [x for x in r["detalle"] if x["pais"] == p and not (NO_SOPORTADO & set(x["esperados"]))]
        ne = sum(1 for x in xs if (set(x["producidos"]) & DERIVACIONES) - set(x["esperados"]))
        out[p] = {"documentos": len(xs), "derivados": sum(x["estado"] == "REVISION_HUMANA" for x in xs),
                  "derivados_incertidumbre": ne, "ic95_incertidumbre": cp(ne, len(xs)),
                  "alerta_injustificada": sum(1 for x in xs if (set(x["producidos"]) & ALERTAS) - set(x["esperados"]))}
    return out


def formato_fecha(t: str) -> str:
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", t):
        return "fecha:anio_2"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t):
        return "fecha:dd/mm/aaaa"
    if re.fullmatch(r"\d{4}[/-]\d{2}[/-]\d{2}", t):
        return "fecha:aaaa/mm/dd"
    if t.startswith("le "):
        return "fecha:fr_textual"
    if re.match(r"[^\W\d_]", t):
        return "fecha:mes_primero"
    return "fecha:coma" if "," in t else "fecha:otra"


def por_condicion(corpus: str, r: dict) -> dict:
    """Documentos, derivados y con alerta injustificada por condición adversarial."""
    meta = json.loads((BASE / corpus / "verdad.json").read_text(encoding="utf-8"))
    det = {x["id"]: x for x in r["detalle"]}
    out = defaultdict(Counter)
    for d in meta["documentos"]:
        x = det[d["id"]]
        pref = d["tipo"][:3]
        claves = [formato_fecha(k[6:]) if k.startswith("fecha:") else f"{pref}:{k}" for k in d["condiciones"]]
        if pref == "pas" and not claves:
            claves = ["pas:(ninguna)"]
        injust = bool((set(x["producidos"]) & ALERTAS) - set(x["esperados"]))
        for k in claves:
            out[k]["n"] += 1
            out[k]["derivados"] += x["estado"] == "REVISION_HUMANA"
            out[k]["alerta_injustificada"] += injust
            out[k]["omision"] += bool(set(x["esperados"]) - set(x["producidos"]))
    return {k: dict(v) for k, v in out.items()}


def tabla_condiciones(resumen: dict) -> str:
    filas, grupo = [], None
    for g, k, desc in CONDICIONES:
        if g != grupo:
            filas.append(f"\\multicolumn{{7}}{{l}}{{\\textit{{{g}}}}} \\\\")
            grupo = g
        celdas = []
        for et in CORPUS:
            v = resumen[et]["por_condicion"].get(k, {"n": 0, "derivados": 0, "alerta_injustificada": 0})
            celdas += [str(v["n"]), str(v["derivados"]), str(v["alerta_injustificada"])]
        filas.append(f"\\quad {desc} & " + " & ".join(celdas) + " \\\\")
    return "\n".join(filas) + "\n"


DETECCION = [  # (tipo de documento, código, descripción, depende de la lectura del contenido)
    ("pasaporte", "PASAPORTE_VENCIDO", "Vencido", True),
    ("pasaporte", "NOMBRE_NO_COINCIDE", "Nombre de otra persona", True),
    ("pasaporte", "NOMBRE_CASI_COINCIDE", "Nombre casi igual", True),
    ("antecedentes_extranjero", "DOCUMENTO_ANTIGUO", "Más de 60 días", True),
    ("antecedentes_extranjero", "SIN_APOSTILLA", "Sin apostilla", True),
    ("antecedentes_extranjero", "SIN_LEGALIZACION", "Sin legalización", True),
    ("antecedentes_extranjero", "NOMBRE_NO_COINCIDE", "Nombre de otra persona", True),
    ("antecedentes_extranjero", "NOMBRE_CASI_COINCIDE", "Nombre casi igual", True),
    ("antecedentes_extranjero", "IDIOMA_NO_SOPORTADO", "Criollo declarado como criollo", True),
    ("antecedentes_extranjero", "DOCUMENTO_NO_RECONOCIDO", "Criollo declarado como francés", True),
    ("liquidacion", "DOCUMENTO_ANTIGUO", "Más de 30 días", True),
    ("liquidacion", "FIRMA_INVALIDA", "Contenido firmado alterado", False),
    ("liquidacion", "MODIFICADO_TRAS_FIRMA", "Contenido agregado tras firmar", False),
    ("liquidacion", "FIRMANTE_NO_ACREDITADO", "Prestador no acreditado", False),
    ("liquidacion", "FIRMANTE_NO_COINCIDE", "Firmada por otro empleador", False),
    ("liquidacion", "SIN_FEA", "Sin firma", False),
    ("certificado_publico_cl", "CODIGO_INEXISTENTE", "Código inexistente", False),
    ("certificado_publico_cl", "CODIGO_DE_OTRA_PERSONA", "Código de otra persona", False),
    ("certificado_publico_cl", "NOMBRE_CASI_COINCIDE", "Titular casi igual", False),
    ("certificado_publico_cl", "DOCUMENTO_ANTIGUO", "Más de 60 días", False),
]
NOMBRE_TIPO = {"pasaporte": "Pasaportes", "antecedentes_extranjero": "Certificados de antecedentes",
               "liquidacion": "Liquidaciones de sueldo", "certificado_publico_cl": "Certificados chilenos con QR"}
EVAL_DETECCION = ["D (it. 4)", "ADV (it. 4)", "ADV2 (it. 5)"]


def deteccion(r: dict) -> dict:
    """Problemas introducidos y detectados, por tipo de documento y código."""
    out = defaultdict(Counter)
    for x in r["detalle"]:
        for c in x["esperados"]:
            out[f"{x['tipo']}|{c}"]["n"] += 1
            out[f"{x['tipo']}|{c}"]["detectados"] += c in x["producidos"]
    return {k: dict(v) for k, v in out.items()}


def tabla_deteccion(resumen: dict) -> str:
    def celda(v):
        return f"{v['detectados']}/{v['n']}" if v["n"] else "--"

    def suma(et, filtro):
        n = d = 0
        for tipo, cod, _, lectura in DETECCION:
            v = resumen[et]["deteccion"].get(f"{tipo}|{cod}", {"n": 0, "detectados": 0})
            if filtro(lectura):
                n += v["n"]; d += v["detectados"]
        pct = f" ({100 * d / n:.0f}\\,\\%)" if n else ""
        return f"{d}/{n}{pct}"

    filas, tipo_ant = [], None
    for tipo, cod, desc, _ in DETECCION:
        if tipo != tipo_ant:
            filas.append(f"\\multicolumn{{4}}{{l}}{{\\textit{{{NOMBRE_TIPO[tipo]}}}}} \\\\")
            tipo_ant = tipo
        celdas = [celda(resumen[et]["deteccion"].get(f"{tipo}|{cod}", {"n": 0, "detectados": 0}))
                  for et in EVAL_DETECCION]
        filas.append(f"\\quad {desc} & " + " & ".join(celdas) + " \\\\")
    filas.append("\\midrule")
    filas.append("Dependen de la lectura del contenido & " + " & ".join(suma(e, lambda l: l) for e in EVAL_DETECCION) + " \\\\")
    filas.append("Detectados por firma o por el emisor & " + " & ".join(suma(e, lambda l: not l) for e in EVAL_DETECCION) + " \\\\")
    filas.append("\\textbf{Total} & " + " & ".join(suma(e, lambda l: True) for e in EVAL_DETECCION) + " \\\\")
    return "\n".join(filas) + "\n"


def main():
    resumen = {}
    for et, d in EVAL.items():
        r = cargar(d); t = r["totales"]
        resumen[et] = {
            "documentos": t["documentos"], "esperados": t["esperados"], "detectados": t["detectados"],
            "omisiones_silenciosas": t["omisiones_silenciosas"], "omisiones_con_derivacion": t["omisiones_con_derivacion"],
            "docs_alerta_injustificada": t["documentos_con_alerta_injustificada"],
            "ic95_docs_alerta_injustificada": t["ic95_doc_alerta_injustificada"],
            "alertas": t["alertas"], "alertas_injustificadas": t["alertas_injustificadas"],
            "derivados": t["documentos_derivados"], "prevalidados": t["prevalidados"],
            "mrz_validas": sum(v["valida"] for k, v in r["mrz"].items() if not k.startswith("deg")),
            "mrz_exactas": sum(v.get("exacta", 0) for k, v in r["mrz"].items() if not k.startswith("deg")),
            "pasaportes": sum(v["n"] for k, v in r["mrz"].items() if not k.startswith("deg")),
            "qr": r["qr"], "firma": {k: [v["correcta"], v["n"]] for k, v in r["firma_por_variante"].items()},
            "campos": {i: {k: v[k] for k in ("campos", "aceptados", "correctos_aceptados_estricto",
                                             "correctos_aceptados_funcional", "precision", "precision_funcional",
                                             "ic95_cp", "lim_inf_unilateral", "ic95_bootstrap_documentos", "cobertura")}
                       for i, v in r["campos_umbral_defecto"].items()},
            "umbrales_calibrados": r["umbrales_calibrados"],
            "latencia": r["latencia_documentos_ocr_prueba_s"],
            "por_pais": por_pais(r),
            "deteccion": deteccion(r),
            "bitacora": r["bitacora"],
        }
        if et in CORPUS:
            resumen[et]["por_condicion"] = por_condicion(CORPUS[et], r)
            todos = sum(1 for x in r["detalle"] if (set(x["producidos"]) & ALERTAS) - set(x["esperados"]))
            assert todos == t["documentos_con_alerta_injustificada"], (et, todos)
        ne = sum(1 for x in r["detalle"] if (set(x["producidos"]) & DERIVACIONES) - set(x["esperados"]))
        assert ne == t["documentos_con_derivacion_no_esperada"], (et, ne)
    (BASE / "resultados_resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    out = BASE / "figuras"; out.mkdir(exist_ok=True)
    (out / "tabla_condiciones.tex").write_text(tabla_condiciones(resumen), encoding="utf-8")
    (out / "tabla_deteccion.tex").write_text(tabla_deteccion(resumen), encoding="utf-8")
    for et in resumen:  # la tabla de detección cubre todos los códigos esperados
        cubiertos = {f"{t}|{c}" for t, c, _, _ in DETECCION}
        assert set(resumen[et]["deteccion"]) <= cubiertos, (et, set(resumen[et]["deteccion"]) - cubiertos)
        tot = sum(v["n"] for v in resumen[et]["deteccion"].values())
        assert tot == resumen[et]["esperados"], (et, tot)
    plt.rcParams.update({"font.size": 9.5, "axes.labelsize": 9.5, "xtick.labelsize": 9.5, "ytick.labelsize": 9})

    # Figura A: comparación de evaluaciones
    ets = ["D (it. 4)", "ADV (it. 4)", "ADV2 (it. 5)"]  # D (it. 5) es idéntico a D (it. 4)
    etiquetas = ["Desarrollo D\n(it. 4)", "Adversarial ADV\n(it. 4, código congelado)", "Adversarial ADV2\n(it. 5)"]
    det = [100 * resumen[e]["detectados"] / resumen[e]["esperados"] for e in ets]
    der = [100 * resumen[e]["derivados"] / resumen[e]["documentos"] for e in ets]
    inj = [100 * resumen[e]["docs_alerta_injustificada"] / resumen[e]["documentos"] for e in ets]
    sil = [100 * resumen[e]["omisiones_silenciosas"] / resumen[e]["documentos"] for e in ets]
    x = np.arange(len(ets)); w = 0.2
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    for k, (vals, lab, col) in enumerate([(det, "Problemas detectados", "#1f4e79"),
                                          (der, "Documentos derivados", "#9dc3e6"),
                                          (inj, "Documentos con alerta injustificada", "#c55a11"),
                                          (sil, "Omisiones silenciosas", "#404040")]):
        b = ax.bar(x + (k - 1.5) * w, vals, w, label=lab, color=col)
        for xi, v in zip(x + (k - 1.5) * w, vals):
            txt = f"{v:.0f}" if v == 0 or v >= 1 else f"{v:.1f}".replace(".", ",")
            ax.text(xi, v + 1.5, txt, ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(etiquetas); ax.set_ylabel("%"); ax.set_ylim(0, 112)
    ax.legend(fontsize=8.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.25), frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(out / "fig_evaluaciones.pdf"); fig.savefig(out / "fig_evaluaciones.png", dpi=150)

    # Figura B: derivación por incertidumbre de lectura por país (sin documentos en criollo)
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    series = [("D (it. 4)", "#d9d9d9", "Desarrollo D (it. 4)"), ("ADV (it. 4)", "#9dc3e6", "Adversarial ADV (it. 4)"),
              ("ADV2 (it. 5)", "#1f4e79", "Adversarial ADV2 (it. 5)")]
    w = 0.27
    for k, (et, col, lab) in enumerate(series):
        pp = resumen[et]["por_pais"]
        vals = [100 * pp[p]["derivados_incertidumbre"] / pp[p]["documentos"] for p in PAISES]
        lo = [v - 100 * pp[p]["ic95_incertidumbre"][0] for v, p in zip(vals, PAISES)]
        hi = [100 * pp[p]["ic95_incertidumbre"][1] - v for v, p in zip(vals, PAISES)]
        xs = np.arange(5) + (k - 1) * w
        ax.bar(xs, vals, w, label=lab, color=col, yerr=[lo, hi], capsize=2, error_kw={"elinewidth": 0.7, "ecolor": "#555"})
        for xi, p, v, h in zip(xs, PAISES, vals, hi):
            txt = f"{pp[p]['derivados_incertidumbre']}/{pp[p]['documentos']}"
            if v > 0:
                ax.text(xi, 2, txt, ha="center", va="bottom", fontsize=7, rotation=90,
                        color="white" if col == "#1f4e79" else "black")
            else:  # barra nula: la etiqueta va sobre el intervalo
                ax.text(xi, v + h + 1.5, txt, ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set_xticks(np.arange(5)); ax.set_xticklabels([NOMBRE_PAIS[p] for p in PAISES])
    ax.set_ylabel("Derivados por incertidumbre (%)"); ax.set_ylim(0, 100)
    ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.17), ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(out / "fig_derivacion_pais.pdf"); fig.savefig(out / "fig_derivacion_pais.png", dpi=150)
    print(json.dumps({e: resumen[e]["por_pais"] for e in resumen}, ensure_ascii=False))


if __name__ == "__main__":
    main()
