"""Extracción de campos a partir de las líneas del OCR o del texto de un PDF firmado.

Cada campo extraído conserva la confianza de la línea de la que proviene; la
calibración del umbral opera sobre esa confianza.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from rapidfuzz.distance import Levenshtein

from . import mrz as mrzmod
from .ocr import Linea, ResultadoOCR


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

# Campos que usan las reglas (los demás se extraen solo para el funcionario).
CAMPOS_USADOS = {"antecedentes": ("nombre", "fecha_emision"),
                 "liquidacion": ("nombre", "fecha_emision", "rut_empleador")}


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def buscar_campo(ocr: ResultadoOCR, patrones: list[str]) -> Campo | None:
    """Busca una etiqueta al inicio de una línea.

    La etiqueta debe terminar en un límite de palabra y estar seguida de un separador
    (":" o ";"), de dos o más espacios o del fin de la línea; así "Nombre del padre:" no
    se confunde con "Nombre:" ni "NOMBRE" con la etiqueta francesa "Nom". Si la línea de
    la etiqueta no tiene valor, se toma la línea siguiente (etiqueta y valor en líneas
    separadas), salvo que esta sea a su vez otra etiqueta."""
    lineas = ocr.lineas
    for i, l in enumerate(lineas):
        t = l.texto.strip()
        for p in patrones:
            m = re.match(rf"^\s*{p}\b\s*(?:[:;]|\s{{2,}}|$)\s*(.*)$", t, flags=re.I)
            if not m:
                continue
            valor = m.group(1).strip(" :;.-")
            if valor:
                return Campo("", valor, l.confianza)
            if i + 1 < len(lineas):
                sig = lineas[i + 1].texto.strip()
                if sig and not sig.endswith(":"):
                    return Campo("", sig.strip(" :;.-"), min(l.confianza, lineas[i + 1].confianza))
            return None
    return None


def extraer_etiquetados(ocr: ResultadoOCR, tipo: str) -> dict[str, Campo]:
    out = {}
    for campo, pats in ETIQUETAS[tipo].items():
        c = buscar_campo(ocr, pats)
        out[campo] = Campo(campo, c.valor if c and c.valor else None, c.confianza if c and c.valor else 0.0)
    return out


def desde_texto(texto: str, motor: str = "pdf") -> ResultadoOCR:
    """Convierte el texto de un PDF (con firma válida) en líneas de confianza 1."""
    return ResultadoOCR(motor, [Linea(l.strip(), 1.0) for l in texto.splitlines() if l.strip()])


# ------------------------------------------------------------------ fechas
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
          "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}


def _fecha(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parsear_fecha(s: str | None) -> date | None:
    """Interpreta fechas numéricas (dd/mm/aaaa, dd-mm-aaaa, dd.mm.aaaa, aaaa-mm-dd) y
    textuales en español y francés ("1 de marzo de 2026", "01 de marzo del 2026",
    "1er mars 2026", "1° de marzo de 2026", "3 de agosto, 2026", "Septiembre 16 de 2026"). Devuelve None si no puede interpretarla:
    las reglas tratan ese caso como lectura no confiable y derivan a revisión humana."""
    if not s:
        return None
    t = _sin_tildes(s.lower())
    t = re.sub(r"(?<=[\d/\-.])o|o(?=[\d/\-.])", "0", t)  # confusión O/0 junto a dígitos
    m = re.search(r"\b(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\b", t)
    if m:
        return _fecha(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b", t)
    if m:
        return _fecha(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s*(?:er|°|º|o)?\s+(?:de\s+)?([a-z]+)\s*,?\s+(?:de\s+|del\s+)?(\d{4})\b", t)
    if m and m.group(2) in _MESES:
        return _fecha(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    m = re.search(r"\b([a-z]+)\s+(\d{1,2})\s*(?:de\s+|,\s*)(\d{4})\b", t)  # "Septiembre 16 de 2026"
    if m and m.group(1) in _MESES:
        return _fecha(int(m.group(3)), _MESES[m.group(1)], int(m.group(2)))
    return None  # incluye años de dos dígitos: ambiguos, se derivan a revisión humana


# ------------------------------------------------------------------ nombres
def normalizar_nombre(s: str | None) -> str:
    """Forma canónica usada por las reglas: mayúsculas, sin tildes, Ñ como N y
    guiones como espacios (así transcribe la MRZ)."""
    return mrzmod.transliterar(s or "")


def _distancia_umbral(t: str) -> int:
    return 1 if len(t) <= 6 else 2


def comparar_nombres(a: str | None, b: str | None, ultimo_truncado_a: bool = False) -> str:
    """Compara dos nombres token a token, sin considerar el orden.

    Devuelve:
      EXACTO       todos los tokens coinciden;
      SUBCONJUNTO  coinciden todos los tokens del nombre más corto (al menos 2) y al
                   más largo le sobra un solo token (p. ej., un segundo nombre omitido);
      CASI         algún token difiere en 1 o 2 caracteres, o sobran 2 o más tokens:
                   puede ser un error de lectura o una persona distinta -> revisión humana;
      DISTINTO     algún token no tiene un par cercano -> alerta.
    `ultimo_truncado_a` indica que el último token de `a` puede estar truncado (MRZ).
    """
    ta, tb = normalizar_nombre(a).split(), normalizar_nombre(b).split()
    if not ta or not tb:
        return "DISTINTO"
    corto, largo, trunc = (ta, tb, ultimo_truncado_a) if len(ta) <= len(tb) else (tb, ta, False)
    libres = list(largo)
    estado = "EXACTO"
    for i, t in enumerate(corto):
        es_trunc = trunc and i == len(corto) - 1
        exacto = next((u for u in libres if u == t or (es_trunc and u.startswith(t))), None)
        if exacto is not None:
            libres.remove(exacto)
            continue
        mejor = min(libres, key=lambda u: Levenshtein.distance(t, u)) if libres else None
        if mejor is not None and Levenshtein.distance(t, mejor) <= _distancia_umbral(t):
            libres.remove(mejor)
            estado = "CASI"
        else:
            return "DISTINTO"
    sobran = len(libres)
    if estado == "CASI":
        return "CASI"
    if sobran == 0:
        return "EXACTO"
    if sobran == 1 and len(corto) >= 2:
        return "SUBCONJUNTO"
    return "CASI"


# ------------------------------------------------------- apostilla/legalización
def detectar_autenticacion(ocr: ResultadoOCR) -> dict[str, bool]:
    """Detecta la presencia (no la autenticidad) de una apostilla o de una legalización.

    Apostilla: la palabra "apostille/apostilla" y la mención a la Convención de La Haya
    de 1961, que el certificado de apostilla debe contener. Legalización: la palabra
    "legalización/légalisation/legalizado" junto a un consulado o ministerio."""
    txt = _sin_tildes(ocr.texto.lower())
    apostilla = bool(re.search(r"apostill[ea]", txt)) and bool(
        re.search(r"(convention de la haye|convencion de la haya|hague convention|5 (?:de )?octob?re (?:de )?1961)", txt))
    legalizacion = bool(re.search(r"(legaliza|legalisa|legalise)", txt)) and bool(
        re.search(r"(consulad|consulat|ministerio de relaciones|ministere des affaires)", txt))
    return {"apostilla": apostilla, "legalizacion": legalizacion}


# ------------------------------------------------------------------- MRZ
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


_CONFUSIONES_NUM = str.maketrans({"G": "6", "O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                                  "Z": "2", "S": "5", "B": "8"})


def casi_igual_numero(a: str, b: str) -> bool:
    """True si dos números de documento difieren solo en caracteres que el OCR confunde
    y que el dígito de control no siempre detecta (p. ej., G y 6)."""
    return len(a) == len(b) and a != b and a.translate(_CONFUSIONES_NUM) == b.translate(_CONFUSIONES_NUM)
