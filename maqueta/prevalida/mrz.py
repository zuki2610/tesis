"""Validación de la zona de lectura mecánica (MRZ) de pasaportes TD3 según OACI Doc 9303.

Una MRZ TD3 tiene dos líneas de 44 caracteres y cinco dígitos de control:
número de documento, fecha de nacimiento, fecha de vencimiento,
número personal (datos opcionales) y dígito compuesto.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

PESOS = (7, 3, 1)


def valor(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - ord("A") + 10
    if c == "<":
        return 0
    raise ValueError(f"Carácter no válido en MRZ: {c!r}")


def digito_control(campo: str) -> int:
    return sum(valor(c) * PESOS[i % 3] for i, c in enumerate(campo)) % 10


def _fecha_yymmdd(s: str, futuro: bool) -> date | None:
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:])
    hoy_yy = date.today().year % 100
    if futuro:
        siglo = 2000
    else:
        siglo = 1900 if yy > hoy_yy else 2000
    try:
        return date(siglo + yy, mm, dd)
    except ValueError:
        return None


@dataclass
class ResultadoMRZ:
    linea1: str
    linea2: str
    pais_emisor: str = ""
    apellidos: str = ""
    nombres: str = ""
    numero: str = ""
    nacionalidad: str = ""
    nacimiento: date | None = None
    sexo: str = ""
    vencimiento: date | None = None
    numero_personal: str = ""
    controles: dict = field(default_factory=dict)

    @property
    def nombre_truncado(self) -> bool:
        """El campo de nombre ocupa toda la línea: el último nombre puede estar truncado."""
        return self.linea1[43] != "<"

    @property
    def valida(self) -> bool:
        return bool(self.controles) and all(self.controles.values())


# Correcciones típicas de OCR en zonas numéricas de la MRZ
_A_DIGITO = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})


_A_LETRA = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})


def normalizar_linea(s: str) -> str:
    s = s.upper().replace(" ", "")
    s = s.replace("«", "<").replace("‹", "<").replace("(", "<").replace("{", "<")
    s = re.sub(r"[^A-Z0-9<]", "<", s)
    return s


def encontrar_mrz(texto: str) -> tuple[str, str] | None:
    """Busca dos líneas consecutivas con forma de MRZ TD3 en el texto del OCR."""
    lineas = [normalizar_linea(l) for l in texto.splitlines() if l.strip()]
    for i in range(len(lineas) - 1):
        a, b = lineas[i], lineas[i + 1]
        if a.startswith("P") and len(a) >= 40 and len(b) >= 40:
            return a[:44].ljust(44, "<"), b[:44].ljust(44, "<")
    return None


def parsear(linea1: str, linea2: str) -> ResultadoMRZ:
    l1, l2 = linea1.ljust(44, "<")[:44], linea2.ljust(44, "<")[:44]
    # Las posiciones numéricas se corrigen con la tabla de confusiones habituales.
    num = l2[0:9]
    dc_num = l2[9].translate(_A_DIGITO)
    nac = l2[13:19].translate(_A_DIGITO)
    dc_nac = l2[19].translate(_A_DIGITO)
    ven = l2[21:27].translate(_A_DIGITO)
    dc_ven = l2[27].translate(_A_DIGITO)
    personal = l2[28:42]
    dc_per = l2[42].translate(_A_DIGITO)
    dc_comp = l2[43].translate(_A_DIGITO)
    nacion = l2[10:13].translate(_A_LETRA)  # códigos de país: solo letras
    l2c = num + dc_num + nacion + nac + dc_nac + l2[20] + ven + dc_ven + personal + dc_per + dc_comp

    # En los nombres no hay dígitos: se corrigen las confusiones inversas (0->O, 1->I, ...).
    nombres_raw = l1[5:].translate(_A_LETRA).split("<<", 1)
    r = ResultadoMRZ(
        linea1=l1, linea2=l2c, pais_emisor=l1[2:5].translate(_A_LETRA).replace("<", ""),
        apellidos=nombres_raw[0].replace("<", " ").strip(),
        nombres=(nombres_raw[1] if len(nombres_raw) > 1 else "").replace("<", " ").strip(),
        numero=num.replace("<", ""), nacionalidad=nacion.replace("<", ""),
        nacimiento=_fecha_yymmdd(nac, futuro=False), sexo=l2[20],
        vencimiento=_fecha_yymmdd(ven, futuro=True), numero_personal=personal.replace("<", ""),
    )

    def ok(campo: str, dc: str) -> bool:
        try:
            return dc.isdigit() and digito_control(campo) == int(dc)
        except ValueError:
            return False

    # El dígito del número personal puede ser '<' cuando el campo está vacío.
    per_ok = (dc_per == "<" and set(personal) <= {"<"}) or ok(personal, dc_per)
    compuesto = num + dc_num + nac + dc_nac + ven + dc_ven + personal + dc_per
    r.controles = {
        "numero": ok(num, dc_num),
        "nacimiento": ok(nac, dc_nac),
        "vencimiento": ok(ven, dc_ven),
        "personal": per_ok,
        "compuesto": ok(compuesto, dc_comp),
    }
    return r


def generar_td3(pais: str, apellidos: str, nombres: str, numero: str, nacionalidad: str,
                nacimiento: date, sexo: str, vencimiento: date, personal: str = "") -> tuple[str, str]:
    """Genera una MRZ TD3 válida (se usa para el corpus sintético y las pruebas)."""
    def mrz_txt(s: str) -> str:
        return transliterar(s).replace(" ", "<").replace("-", "<")

    l1 = f"P<{pais:<3}".replace(" ", "<") + mrz_txt(apellidos) + "<<" + mrz_txt(nombres)
    l1 = l1[:44].ljust(44, "<")
    num = numero.ljust(9, "<")[:9]
    nac = nacimiento.strftime("%y%m%d")
    ven = vencimiento.strftime("%y%m%d")
    per = personal.ljust(14, "<")[:14]
    dper = str(digito_control(per)) if personal else "<"
    base = num + str(digito_control(num)) + nacionalidad.ljust(3, "<") + nac + str(digito_control(nac)) + sexo \
        + ven + str(digito_control(ven)) + per + dper
    comp = num + str(digito_control(num)) + nac + str(digito_control(nac)) + ven + str(digito_control(ven)) + per + dper
    l2 = base + str(digito_control(comp))
    return l1, l2


def transliterar(s: str) -> str:
    """Normalización de nombres al estilo MRZ: mayúsculas, sin tildes, Ñ como N."""
    s = s.upper().replace("Ñ", "N")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_CLASES_CONFUSION = [set("1IL"), set("0OQD"), set("5S"), set("8B"), set("2Z"), set("6G")]


def _confundibles(x: str, y: str) -> bool:
    return x == y or any(x in c and y in c for c in _CLASES_CONFUSION)


def parsear_con_reparacion(linea1: str, linea2: str) -> tuple[ResultadoMRZ, bool]:
    """Interpreta la MRZ y, si los dígitos de control fallan porque el OCR leyó un
    carácter como dos (p. ej. "I" como "1I"), la segunda línea queda con 45 caracteres.
    Se prueba eliminar solo caracteres contiguos a uno confundible con él y se acepta
    la reparación únicamente si existe una sola variante que valida los cinco
    dígitos de control.

    Devuelve (resultado, reparada)."""
    r = parsear(linea1, linea2)
    if r.valida or len(linea2) != 45:
        return r, False
    validas: dict[str, ResultadoMRZ] = {}
    for k in range(45):
        vecinos = [linea2[j] for j in (k - 1, k + 1) if 0 <= j < 45]
        if not any(_confundibles(linea2[k], v) and linea2[k] != "<" for v in vecinos):
            continue
        rc = parsear(linea1, linea2[:k] + linea2[k + 1:])
        if rc.valida:
            validas[rc.linea2] = rc
    if len(validas) == 1:
        return next(iter(validas.values())), True
    return r, False
