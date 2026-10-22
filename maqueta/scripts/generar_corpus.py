"""Genera un corpus sintético de documentos ficticios con verdad de referencia (versión 2).

Ningún documento corresponde a una persona real ni reproduce el diseño oficial de
ningún país: son especímenes genéricos marcados como FICTICIO, con datos inventados.
`verdad.json` contiene los valores correctos de cada campo y los hallazgos esperados.

Cambios respecto de la versión 1: nombres por nacionalidad; MRZ impresa en OCR-B;
legalización (no apostilla) para Haití, que no es parte de la Convención de 1961;
formatos de fecha variados; casos en el límite de los plazos; nombres casi iguales y
segundos nombres omitidos; seis variantes de firma electrónica, incluida la
modificación incremental y la firma de un tercero; documentos en criollo declarados
como francés.

Uso: CORPUS_DIR=corpus_D SEED=20261022 python scripts/generar_corpus.py
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prevalida.mrz import generar_td3  # noqa: E402

RAIZ = Path(os.environ.get("CORPUS_DIR", Path(__file__).resolve().parent.parent / "corpus"))
FECHA_PRESENTACION = date(2026, 10, 1)
SEED = int(os.environ.get("SEED", "20261022"))
# Tamaños del corpus (por defecto, los del corpus de desarrollo D). Permiten generar corpus con
# una muestra planificada, por ejemplo para medir RNF-04 con al menos 299 campos por idioma.
N_PASAPORTES = int(os.environ.get("N_PASAPORTES", "24"))          # por país
N_ANTECEDENTES = int(os.environ.get("N_ANTECEDENTES", "24"))      # por país de habla hispana
N_ANTECEDENTES_HTI = int(os.environ.get("N_ANTECEDENTES_HTI", os.environ.get("N_ANTECEDENTES", "24")))
N_LIQ_POR_VARIANTE = int(os.environ.get("N_LIQ_POR_VARIANTE", "10"))
N_QR = int(os.environ.get("N_QR", "40"))
N_CRIOLLO = int(os.environ.get("N_CRIOLLO", "10"))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OCRB = "/usr/share/fonts/opentype/ocr-b/OCRB.otf"

PAISES = {"VEN": ("es", "VENEZUELA"), "PER": ("es", "PERÚ"), "COL": ("es", "COLOMBIA"),
          "BOL": ("es", "BOLIVIA"), "HTI": ("fr", "HAÏTI")}
NOMBRES = {
    "VEN": (["María José", "Luis Alberto", "Yohana", "José Gregorio", "Daniela", "Carlos Eduardo", "Andreína",
             "Jesús Alberto"],
            ["Pérez", "González", "Rodríguez", "Hernández", "García", "Martínez", "Rojas", "Gutiérrez", "Ibáñez",
             "Núñez"]),
    "PER": (["Ana Lucía", "Juan Carlos", "Rosa", "Luis Miguel", "Milagros", "Jorge Luis", "Yesenia"],
            ["Quispe", "Mamani", "Flores", "Huamán", "Castañeda", "Sánchez", "Vargas", "Chávez"]),
    "COL": (["Andrés Felipe", "Luz Marina", "Diana Carolina", "Juan David", "Paola Andrea", "Jhon Jairo"],
            ["Rodríguez", "Gómez", "Martínez", "López", "Muñoz", "Valencia", "Cárdenas", "Ospina"]),
    "BOL": (["Ñuflo", "Carmen Rosa", "Wilson", "Fabiola", "Freddy", "Mónica", "Edwin"],
            ["Mamani", "Quispe", "Choque", "Condori", "Flores", "Vargas", "Gutiérrez", "Copa"]),
    "HTI": (["Kervens", "Guerline", "Jean Pierre", "Rose Marie", "Wisly", "Nadège", "Marie Michelle", "Jean Baptiste"],
            ["Joseph", "Louis", "Pierre", "Jean-Baptiste", "Saint-Fleur", "Dorvil", "Célestin", "Exantus",
             "Toussaint", "Augustin"]),
}
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
            "noviembre", "diciembre"]
MESES_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
            "novembre", "décembre"]
DEGRADACIONES = ["limpio", "escaner", "celular", "baja_res"]

rng = random.Random(SEED)
nprng = np.random.default_rng(SEED)


def f(ruta, tam):
    return ImageFont.truetype(ruta, tam)


# ----------------------------------------------------------------- nombres
def persona(pais: str) -> tuple[str, str]:
    nombres, apellidos = NOMBRES[pais]
    n_ap = 1 if pais == "HTI" and rng.random() < 0.6 else 2
    return rng.choice(nombres), " ".join(rng.sample(apellidos, n_ap))


def _lev(a: str, b: str) -> int:
    """Distancia de edición propia del generador (independiente del sistema evaluado)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _tokens(s: str) -> list[str]:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.upper().replace("Ñ", "N").replace("-", " "))
    return "".join(c for c in s if not unicodedata.combining(c)).split()


def persona_distinta(pais: str, nombre: str) -> str:
    """Otra persona cuyos tokens están todos a distancia > 2 de los del nombre original."""
    orig = _tokens(nombre)
    for _ in range(500):
        n, a = persona(pais)
        cand = f"{n} {a}"
        if all(_lev(t, u) > 2 for t in _tokens(cand) for u in orig):
            return cand
    raise RuntimeError("No se encontró una persona distinta")


def nombre_casi(nombre: str) -> str:
    """Cambia una letra interior de un apellido (distancia de edición 1)."""
    partes = nombre.split()
    i = rng.randrange(len(partes) // 2, len(partes))  # un apellido
    t = partes[i]
    pos = rng.randrange(1, len(t))
    letras = "abcdefghijlmnoprstuvz"
    nueva = rng.choice([c for c in letras if c != t[pos].lower()])
    partes[i] = t[:pos] + nueva + t[pos + 1:]
    return " ".join(partes)


def variante_nombre(nombre_doc: str, pais: str) -> tuple[str, list[str]]:
    """Nombre declarado y hallazgo esperado: 10 % otra persona, 8 % casi igual,
    8 % segundo nombre omitido (no debe generar hallazgos), resto idéntico."""
    x = rng.random()
    if x < 0.10:
        return persona_distinta(pais, nombre_doc), ["NOMBRE_NO_COINCIDE"]
    if x < 0.18:
        return nombre_casi(nombre_doc), ["NOMBRE_CASI_COINCIDE"]
    partes = nombre_doc.split()
    if x < 0.26 and len(partes) >= 4:
        return " ".join([partes[0]] + partes[2:]), []
    return nombre_doc, []


# ------------------------------------------------------------------ fechas
def fecha_txt(d: date, idioma: str) -> str:
    if idioma == "fr":
        k = rng.randrange(3)
        if k == 0:
            return d.strftime("%d/%m/%Y")
        dia = "1er" if d.day == 1 else str(d.day)
        return f"{dia} {MESES_FR[d.month - 1]} {d.year}"
    k = rng.randrange(5)
    return [d.strftime("%d/%m/%Y"), f"{d.day} de {MESES_ES[d.month - 1]} de {d.year}", d.strftime("%d-%m-%Y"),
            d.strftime("%d.%m.%Y"), f"{d.day:02d} de {MESES_ES[d.month - 1]} del {d.year}"][k]


def antiguedad(plazo: int, antiguo: bool) -> int:
    """Días desde la emisión: incluye casos en el límite (plazo, plazo-1, plazo+1, plazo+2)."""
    if antiguo:
        return rng.choice([plazo + 1, plazo + 2]) if rng.random() < 0.3 else rng.randint(plazo + 10, plazo * 5)
    return rng.choice([plazo - 1, plazo]) if rng.random() < 0.15 else rng.randint(2, plazo - 5)


# ------------------------------------------------------------- degradación
def degradar(img: Image.Image, tipo: str) -> Image.Image:
    img = img.convert("L")
    if tipo == "escaner":
        img = img.filter(ImageFilter.GaussianBlur(0.8))
        a = np.array(img, dtype=np.float32) + nprng.normal(0, 10, (img.height, img.width))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    elif tipo == "celular":
        img = img.rotate(rng.uniform(-3.5, 3.5), expand=True, fillcolor=235)
        a = np.array(img, dtype=np.float32)
        a = a * np.linspace(0.75, 1.05, a.shape[1])[None, :] + nprng.normal(0, 6, a.shape)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=40); img = Image.open(buf).convert("L")
    elif tipo == "baja_res":
        w, h = img.size
        img = img.resize((int(w * 0.55), int(h * 0.55)), Image.BILINEAR).resize((w, h), Image.BILINEAR)
    return img


def guardar(img: Image.Image, nombre: str) -> str:
    p = RAIZ / "imagenes" / f"{nombre}.png"
    img.save(p)
    return str(p.relative_to(RAIZ))


# ----------------------------------------------------------------- pasaportes
def pasaporte(i: int, pais: str) -> dict:
    idioma, nombre_pais = PAISES[pais]
    nom, ape = persona(pais)
    num = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(2)) + f"{rng.randint(1000000, 9999999)}"
    nac = date(rng.randint(1960, 2004), rng.randint(1, 12), rng.randint(1, 28))
    vencido = rng.random() < 0.2
    ven = FECHA_PRESENTACION + timedelta(days=rng.randint(-900, -1) if vencido else rng.randint(1, 3000))
    sexo = rng.choice("FM")
    personal = "" if rng.random() < 0.5 else f"{rng.randint(10**8, 10**9 - 1)}"
    l1, l2 = generar_td3(pais, ape, nom, num, pais, nac, sexo, ven, personal)
    declarado, esperados = variante_nombre(f"{nom} {ape}", pais)
    img = Image.new("RGB", (1240, 820), "white"); d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 1230, 810], outline="black", width=3)
    d.text((40, 30), f"{nombre_pais} — PASAPORTE / PASSPORT", font=f(FONT_B, 34), fill="black")
    d.text((40, 80), "ESPÉCIMEN FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 22), fill=(150, 0, 0))
    d.rectangle([40, 130, 300, 470], outline="gray", width=2); d.text((110, 290), "FOTO", font=f(FONT, 28), fill="gray")
    y = 135
    for et, v in [("Apellidos / Surname", ape.upper()), ("Nombres / Given names", nom.upper()),
                  ("Nacionalidad / Nationality", nombre_pais), ("Fecha de nacimiento", nac.strftime("%d/%m/%Y")),
                  ("Sexo / Sex", sexo), ("Fecha de vencimiento", ven.strftime("%d/%m/%Y")), ("N.º de pasaporte", num)]:
        d.text((330, y), et, font=f(FONT, 18), fill="gray"); d.text((330, y + 20), v, font=f(FONT_B, 24), fill="black")
        y += 48
    d.text((40, 660), l1, font=f(OCRB, 25), fill="black")
    d.text((40, 710), l2, font=f(OCRB, 25), fill="black")
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"pas_{pais}_{i:03d}")
    if vencido:
        esperados = esperados + ["PASAPORTE_VENCIDO"]
    return {"id": f"pas_{pais}_{i:03d}", "tipo": "pasaporte", "pais": pais, "idioma": idioma, "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": declarado, "numero_pasaporte_declarado": num},
            "verdad": {"numero": num, "apellidos": ape, "nombres": nom, "vencimiento": ven.isoformat(),
                       "mrz1": l1, "mrz2": l2, "nombre_truncado": l1[43] != "<"}, "esperados": esperados}


# ------------------------------------------------------------- antecedentes
TXT_ANT = {
    "es": {"tit": "CERTIFICADO DE ANTECEDENTES PENALES", "nom": "Nombre", "doc": "N.º de documento",
           "fec": "Fecha de emisión", "fol": "Folio",
           "cuerpo": ["La autoridad competente certifica que la persona individualizada",
                      "no registra antecedentes penales a la fecha de emisión."]},
    "fr": {"tit": "CERTIFICAT DE CASIER JUDICIAIRE", "nom": "Nom et prénoms", "doc": "N° de pièce",
           "fec": "Date de délivrance", "fol": "Certificat N°",
           "cuerpo": ["L'autorité compétente certifie que la personne désignée",
                      "ne fait l'objet d'aucune condamnation à la date de délivrance."]},
}


def antecedentes(i: int, pais: str) -> dict:
    idioma, nombre_pais = PAISES[pais]
    t = TXT_ANT[idioma]
    nom, ape = persona(pais); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FECHA_PRESENTACION - timedelta(days=antiguedad(60, antiguo))
    sin_aut = rng.random() < 0.15
    declarado, esperados = variante_nombre(nombre, pais)
    doc, folio = f"{rng.randint(10**6, 10**8)}", f"{rng.randint(10**5, 10**7)}"
    img = Image.new("RGB", (1240, 1100), "white"); d = ImageDraw.Draw(img)
    d.text((60, 40), nombre_pais, font=f(FONT_B, 30), fill="black")
    d.text((60, 90), t["tit"], font=f(FONT_B, 32), fill="black")
    d.text((60, 140), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 20), fill=(150, 0, 0))
    y = 210
    for linea in t["cuerpo"]:
        d.text((60, y), linea, font=f(FONT, 24), fill="black"); y += 36
    y += 30
    for et, v in [(t["nom"], nombre), (t["doc"], doc), (t["fec"], fecha_txt(emision, idioma)), (t["fol"], folio)]:
        d.text((60, y), f"{et}: {v}", font=f(FONT, 26), fill="black"); y += 50
    if not sin_aut:
        d.rectangle([640, 760, 1180, 1050], outline="black", width=2)
        if pais == "HTI":  # Haití no es parte de la Convención: legalización consular
            d.text((660, 775), "LÉGALISATION", font=f(FONT_B, 28), fill="black")
            d.text((660, 815), "Ministère des Affaires Étrangères et des Cultes", font=f(FONT, 17), fill="black")
            d.text((660, 850), "Consulado de Chile en Puerto Príncipe", font=f(FONT, 18), fill="black")
            d.text((660, 880), f"Legalizado N.º {rng.randint(10**5, 10**6)}", font=f(FONT, 18), fill="black")
        else:
            d.text((660, 775), "APOSTILLE", font=f(FONT_B, 28), fill="black")
            d.text((660, 815), "(Convention de La Haye du 5 octobre 1961)", font=f(FONT, 17), fill="black")
            d.text((660, 850), f"País: {nombre_pais}", font=f(FONT, 18), fill="black")
            d.text((660, 880), f"N.º {rng.randint(10**5, 10**6)}", font=f(FONT, 18), fill="black")
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"ant_{pais}_{i:03d}")
    esperados = esperados + (["DOCUMENTO_ANTIGUO"] if antiguo else []) + \
        ([("SIN_LEGALIZACION" if pais == "HTI" else "SIN_APOSTILLA")] if sin_aut else [])
    return {"id": f"ant_{pais}_{i:03d}", "tipo": "antecedentes_extranjero", "pais": pais, "idioma": idioma,
            "degradacion": deg, "imagen": ruta, "ctx": {"nombre_declarado": declarado},
            "verdad": {"nombre": nombre, "documento": doc, "fecha_emision": emision.isoformat(), "folio": folio,
                       "dias": (FECHA_PRESENTACION - emision).days},
            "esperados": esperados}


# ---------------------------------------------------- liquidaciones (privado)
def crear_pki(dir_: Path, empleadores: list[str]) -> None:
    """Dos autoridades de prueba (una tratada como acreditada) y un certificado por
    empleador con su RUT en el atributo serialNumber."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    ahora = datetime.now(timezone.utc)

    def guardar_pem(nombre, obj, clave=None):
        (dir_ / f"{nombre}.pem").write_bytes(obj.public_bytes(serialization.Encoding.PEM))
        if clave is not None:
            (dir_ / f"clave_{nombre}.pem").write_bytes(clave.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    cas = {}
    for etiqueta, cn in [("acreditada", "Prestador Acreditado de PRUEBA"), ("no_acreditada", "CA No Acreditada de PRUEBA")]:
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        n = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
             .not_valid_after(ahora + timedelta(days=3650))
             .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
             .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
             .sign(k, hashes.SHA256()))
        guardar_pem(f"raiz_{etiqueta}", c)
        cas[etiqueta] = (k, c)
    for idx, rut in enumerate(empleadores + ["70.000.000-0"]):
        etiqueta = "acreditada" if idx < len(empleadores) else "no_acreditada"
        kca, cca = cas[etiqueta]
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        n = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
                       x509.NameAttribute(NameOID.COMMON_NAME, f"Empleador Ficticio {idx}"),
                       x509.NameAttribute(NameOID.SERIAL_NUMBER, rut)])
        c = (x509.CertificateBuilder().subject_name(n).issuer_name(cca.subject).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
             .not_valid_after(ahora + timedelta(days=365))
             .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
             .sign(kca, hashes.SHA256()))
        guardar_pem(f"emp_{idx}", c, k)
        (dir_ / f"emp_{idx}.ca").write_text(etiqueta)


def pdf_liquidacion(lineas: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf, pageCompression=0)
    y = 780
    for l in lineas:
        c.drawString(60, y, l); y -= 22
    c.save(); return buf.getvalue()


def firmar(pdf: bytes, idx: int, dir_: Path) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    etiqueta = (dir_ / f"emp_{idx}.ca").read_text()
    s = signers.SimpleSigner.load(str(dir_ / f"clave_emp_{idx}.pem"), str(dir_ / f"emp_{idx}.pem"),
                                  ca_chain_files=(str(dir_ / f"raiz_{etiqueta}.pem"),))
    return signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)),
                            signers.PdfSignatureMetadata(field_name="FirmaEmpleador"), signer=s).getvalue()


def agregar_incremental(pdf: bytes, texto: str) -> bytes:
    """Agrega contenido visible a la página mediante una actualización incremental, sin volver a firmar."""
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    w = IncrementalPdfFileWriter(io.BytesIO(pdf))
    page = w.root["/Pages"]["/Kids"][0].get_object()
    ref = w.add_object(generic.StreamObject(stream_data=f"BT /F1 14 Tf 300 600 Td ({texto}) Tj ET".encode("latin-1")))
    cont = page["/Contents"]
    page["/Contents"] = generic.ArrayObject((list(cont) if isinstance(cont, generic.ArrayObject) else [cont]) + [ref])
    w.update_container(page)
    out = io.BytesIO(); w.write(out)
    return out.getvalue()


VARIANTES_FIRMA = ["valida", "alterada", "incremental", "no_acreditada", "otro_firmante", "sin_firma"]
ESPERADO_FIRMA = {"valida": [], "alterada": ["FIRMA_INVALIDA"], "incremental": ["MODIFICADO_TRAS_FIRMA"],
                  "no_acreditada": ["FIRMANTE_NO_ACREDITADO"], "otro_firmante": ["FIRMANTE_NO_COINCIDE"],
                  "sin_firma": ["SIN_FEA"]}


def liquidacion(i: int, variante: str, empleadores: list[str], dir_ca: Path) -> dict:
    pais = rng.choice(list(PAISES))
    nom, ape = persona(pais); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FECHA_PRESENTACION - timedelta(days=antiguedad(30, antiguo))
    idx = rng.randrange(len(empleadores))
    rut = empleadores[idx]
    liquido = f"$ {rng.randint(500, 2500)}.{rng.randint(100, 999)}"
    periodo = (emision.replace(day=1) - timedelta(days=1)).strftime("%m/%Y")
    lineas = ["LIQUIDACIÓN DE REMUNERACIONES", "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ",
              f"RUT empleador: {rut}", f"Trabajador: {nombre}", f"Período: {periodo}",
              f"Fecha de emisión: {fecha_txt(emision, 'es')}", f"Líquido a pagar: {liquido}"]
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img); y = 60
    for k, l in enumerate(lineas):
        d.text((60, y), l, font=f(FONT_B if k == 0 else FONT, 30 if k == 0 else 26),
               fill=(150, 0, 0) if k == 1 else "black"); y += 60
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"liq_{i:03d}")
    pdf = pdf_liquidacion(lineas)
    if variante in ("valida", "alterada", "incremental"):
        pdf = firmar(pdf, idx, dir_ca)
    elif variante == "no_acreditada":
        pdf = firmar(pdf, len(empleadores), dir_ca)
    elif variante == "otro_firmante":  # firma válida de otro empleador acreditado
        pdf = firmar(pdf, (idx + 1) % len(empleadores), dir_ca)
    if variante == "alterada":  # cambia un byte del monto dentro del contenido firmado
        p = pdf.find(b"pagar: $ ")
        pdf = pdf[:p + 9] + (b"9" if pdf[p + 9:p + 10] != b"9" else b"8") + pdf[p + 10:]
    if variante == "incremental":
        pdf = agregar_incremental(pdf, "Liquido a pagar corregido: $ 9.999.999")
    p = RAIZ / "pdf" / f"liq_{i:03d}.pdf"; p.write_bytes(pdf)
    esperados = list(ESPERADO_FIRMA[variante]) + (["DOCUMENTO_ANTIGUO"] if antiguo else [])
    return {"id": f"liq_{i:03d}", "tipo": "liquidacion", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "pdf": str(p.relative_to(RAIZ)), "variante_firma": variante,
            "ctx": {"nombre_declarado": nombre},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "rut_empleador": rut,
                       "liquido": liquido, "periodo": periodo, "dias": (FECHA_PRESENTACION - emision).days},
            "esperados": esperados}


# ------------------------------------------- certificados públicos con QR
def certificado_cl(i: int, registro: dict) -> dict:
    nom, ape = persona(rng.choice(list(PAISES))); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.15
    emision = FECHA_PRESENTACION - timedelta(days=antiguedad(60, antiguo))
    folio, codigo = f"{500000 + i}", f"{rng.randint(10**7, 10**8):x}"
    caso = rng.random()
    esperados = []
    titular = nombre
    if caso < 0.12:
        titular = persona_distinta(rng.choice(list(PAISES)), nombre); esperados.append("CODIGO_DE_OTRA_PERSONA")
    elif caso < 0.18:
        titular = nombre_casi(nombre); esperados.append("NOMBRE_CASI_COINCIDE")
    if caso >= 0.18 and caso < 0.28:
        esperados.append("CODIGO_INEXISTENTE")
    else:
        registro[folio] = {"codigo": codigo, "titular": titular, "fecha_emision": emision.isoformat()}
    if antiguo and "CODIGO_INEXISTENTE" not in esperados:
        esperados.append("DOCUMENTO_ANTIGUO")
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img)
    d.text((60, 50), "CERTIFICADO DE NACIMIENTO (FICTICIO)", font=f(FONT_B, 30), fill="black")
    d.text((60, 100), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 20), fill=(150, 0, 0))
    y = 180
    for l in [f"Nombre: {nombre}", f"Fecha de emisión: {emision.strftime('%d/%m/%Y')}", f"Folio: {folio}"]:
        d.text((60, y), l, font=f(FONT, 26), fill="black"); y += 50
    qr = qrcode.make(f"https://verificacion.ejemplo.cl/v?folio={folio}&codigo={codigo}").resize((260, 260))
    img.paste(qr, (900, 560))
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"cl_{i:03d}")
    return {"id": f"cl_{i:03d}", "tipo": "certificado_publico_cl", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": nombre},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "folio": folio},
            "esperados": esperados}


def criollo(i: int, idioma_declarado: str) -> dict:
    """Documento en criollo haitiano. Declarado como 'ht' (no soportado) o como 'fr'
    (la persona elige francés): en ese caso el sistema debe reconocer que no puede leerlo."""
    img = Image.new("RGB", (1240, 700), "white"); d = ImageDraw.Draw(img)
    for k, l in enumerate(["SÈTIFIKA DOSYE JIDISYÈ (DOKIMAN FIKTIF POU TÈS)", "Non konplè: Wisly Dorvil",
                           "Dat: 3 out 2026", "Otorite a sètifye moun sa a pa gen okenn kondanasyon."]):
        d.text((60, 60 + 60 * k), l, font=f(FONT, 28), fill="black")
    ruta = guardar(img.convert("L"), f"ht_{i:03d}")
    esp = ["IDIOMA_NO_SOPORTADO"] if idioma_declarado == "ht" else ["DOCUMENTO_NO_RECONOCIDO"]
    return {"id": f"ht_{i:03d}", "tipo": "antecedentes_extranjero", "pais": "HTI", "idioma": idioma_declarado,
            "degradacion": "limpio", "imagen": ruta, "ctx": {"nombre_declarado": "Wisly Dorvil"},
            "verdad": {}, "esperados": esp}


def main():
    for sub in ("imagenes", "pdf", "certs"):
        (RAIZ / sub).mkdir(parents=True, exist_ok=True)
    empleadores = [f"{rng.randint(76, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.choice('0123456789K')}"
                   for _ in range(8)]
    dir_ca = RAIZ / "certs"; crear_pki(dir_ca, empleadores)
    docs, registro = [], {}
    for pais in PAISES:
        n_ant = N_ANTECEDENTES_HTI if pais == "HTI" else N_ANTECEDENTES
        for i in range(max(N_PASAPORTES, n_ant)):  # con los valores por defecto, el orden original
            if i < N_PASAPORTES:
                docs.append(pasaporte(i, pais))
            if i < n_ant:
                docs.append(antecedentes(i, pais))
    variantes = VARIANTES_FIRMA * N_LIQ_POR_VARIANTE
    rng.shuffle(variantes)
    for i, v in enumerate(variantes):
        docs.append(liquidacion(i, v, empleadores, dir_ca))
    for i in range(N_QR):
        docs.append(certificado_cl(i, registro))
    for i in range(N_CRIOLLO):
        docs.append(criollo(i, "ht" if i % 2 == 0 else "fr"))
    (RAIZ / "emisor_simulado.json").write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"generador": "v2", "fecha_presentacion": FECHA_PRESENTACION.isoformat(), "semilla": SEED,
            "tamanos": {"pasaportes": N_PASAPORTES, "antecedentes": N_ANTECEDENTES,
                        "antecedentes_hti": N_ANTECEDENTES_HTI, "liq_por_variante": N_LIQ_POR_VARIANTE,
                        "qr": N_QR, "criollo": N_CRIOLLO},
            "documentos": docs}
    (RAIZ / "verdad.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(docs)} documentos generados en {RAIZ}")


if __name__ == "__main__":
    main()
