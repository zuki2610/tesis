"""Extracción de campos a partir de las líneas del OCR, por tipo de documento.

Cada campo extraído conserva la confianza de la línea de la que proviene; la
calibración del umbral (sección 10.3 de la tesis) opera sobre esa confianza.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from rapidfuzz.distance import JaroWinkler

from . import mrz as mrzmod
from .ocr import ResultadoOCR


@dataclass
class Campo:
    nombre: str
    valor: str | None
    confianza: float


ETIQUETAS = {
    "antecedentes": {
        "nombre": [r"nombre(?:s)?(?: completo)?", r"nom(?: et pr[ée]noms?)?", r"apellidos? y nombres?"],
        "documento": [r"n\S{0,3}\s*de documento", r"n[uú]mero de documento", r"n\S{0,3}\s*de pi[eè]ce", r"num[ée]ro de pi[eè]ce"],
        "fecha_emision": [r"fecha de emisi[oó]n", r"date (?:de )?d[ée]livrance", r"date d.?[ée]mission", r"emitido el", r"d[ée]livr[ée] le"],
        "folio": [r"folio", r"certificat\s*n\S{0,3}", r"n[uú]mero de certificado"],
    },
    "liquidacion": {
        "rut_empleador": [r"rut empleador"],
        "nombre": [r"trabajador(?:a)?"],
        "periodo": [r"per[ií]odo"],
        "fecha_emision": [r"fecha de emisi[oó]n"],
        "liquido": [r"l[ií]quido a pagar"],
    },
}


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def buscar_campo(ocr: ResultadoOCR, patrones: list[str]) -> Campo | None:
    for l in ocr.lineas:
        t = l.texto.strip()
        for p in patrones:
            m = re.search(rf"^\s*{p}\s*[:;.\-]?\s*(.+)$", t, flags=re.I)
            if m and m.group(1).strip():
                return Campo("", m.group(1).strip(" :;.-"), l.confianza)
    return None


def extraer_etiquetados(ocr: ResultadoOCR, tipo: str) -> dict[str, Campo]:
    out = {}
    for campo, pats in ETIQUETAS[tipo].items():
        c = buscar_campo(ocr, pats)
        out[campo] = Campo(campo, c.valor if c else None, c.confianza if c else 0.0)
    return out


_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
          "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}


def parsear_fecha(s: str | None) -> date | None:
    if not s:
        return None
    t = _sin_tildes(s.lower())
    # Corrige la confusión O/0 solo cuando la letra está junto a dígitos o separadores.
    t = re.sub(r"(?<=[\d/\-.])o|o(?=[\d/\-.])", "0", t)
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})", t)
    if m:
        d, mth, y = map(int, m.groups())
        try:
            return date(y, mth, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de\s+)?(\d{4})", t)
    if m and m.group(2) in _MESES:
        try:
            return date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def normalizar_nombre(s: str | None) -> str:
    """Normaliza un nombre para compararlo con la MRZ: sin tildes, Ñ como N y
    tokens ordenados, de modo que el orden de apellidos y nombres no importe."""
    if not s:
        return ""
    return " ".join(sorted(mrzmod.transliterar(s).split()))


def similitud_nombres(a: str | None, b: str | None) -> float:
    """Similitud entre nombres independiente del orden de los tokens.

    Cada token de un nombre se compara (Jaro-Winkler) con su mejor par en el otro;
    se promedia en ambos sentidos y se toma el mínimo. Así, un error de un carácter
    en un apellido no cambia el orden de comparación del resto."""
    ta, tb = normalizar_nombre(a).split(), normalizar_nombre(b).split()
    if not ta or not tb:
        return 0.0

    def dir_(x, y):
        return sum(max(JaroWinkler.similarity(t, u) for u in y) for t in x) / len(x)

    return min(dir_(ta, tb), dir_(tb, ta))


def detectar_apostilla(ocr: ResultadoOCR) -> tuple[bool, float]:
    """Detecta el texto obligatorio de la apostilla (Convención de La Haya de 1961).

    Solo indica presencia del sello en el documento; no verifica su autenticidad,
    que corresponde al registro electrónico del país emisor cuando existe.
    """
    for l in ocr.lineas:
        t = _sin_tildes(l.texto.lower())
        if "apostille" in t or "apostilla" in t or "convention de la haye" in t or "convencion de la haya" in t:
            return True, l.confianza
    return False, 0.0


def extraer_mrz(ocr: ResultadoOCR) -> tuple[mrzmod.ResultadoMRZ | None, float]:
    """Devuelve la primera MRZ candidata con todos sus dígitos de control válidos;
    si ninguna es válida, la primera encontrada (para derivarla a revisión humana)."""
    lineas = [mrzmod.normalizar_linea(l.texto) for l in ocr.lineas]
    primera = None
    for i in range(len(lineas) - 1):
        a, b = lineas[i], lineas[i + 1]
        if a.startswith("P") and len(a) >= 38 and len(b) >= 38:
            conf = min(ocr.lineas[i].confianza, ocr.lineas[i + 1].confianza)
            r, _ = mrzmod.parsear_con_reparacion(a[:44], b[:45])
            if r.valida:
                return r, conf
            primera = primera or (r, conf)
    return primera if primera else (None, 0.0)
