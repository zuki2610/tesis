"""Genera un corpus sintético de documentos ficticios con verdad de referencia.

Ningún documento corresponde a una persona real ni reproduce el diseño oficial de
ningún país: son especímenes genéricos marcados como FICTICIO, con datos inventados.
Cada documento incluye en `verdad.json` los valores correctos de sus campos y los
hallazgos que el sistema debería producir.
"""
from __future__ import annotations

import io
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prevalida.mrz import generar_td3  # noqa: E402

import os
RAIZ = Path(os.environ.get("CORPUS_DIR", Path(__file__).resolve().parent.parent / "corpus"))
FECHA_PRESENTACION = date(2026, 10, 1)
SEED = int(os.environ.get("SEED", "20261019"))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

PAISES = {"VEN": ("es", "VENEZUELA"), "PER": ("es", "PERÚ"), "COL": ("es", "COLOMBIA"),
          "BOL": ("es", "BOLIVIA"), "HTI": ("fr", "HAÏTI")}
NOMBRES = ["María José", "Luis Alberto", "Ana Lucía", "José Ángel", "Carmen Rosa", "Jean Pierre", "Rose Marie",
           "Juan Carlos", "Daniela", "Wilson", "Yohana", "Ñuflo", "Fabiola", "Kervens", "Guerline", "Andrés Felipe"]
APELLIDOS = ["Pérez", "González", "Rodríguez", "Muñoz", "Quispe", "Mamani", "Jean-Baptiste", "Pierre", "Martínez",
             "Hernández", "Ibáñez", "Castañeda", "Joseph", "Louis", "Valdés", "Gutiérrez", "Núñez", "Saint-Fleur"]
DEGRADACIONES = ["limpio", "escaner", "celular", "baja_res"]

rng = random.Random(SEED)
nprng = np.random.default_rng(SEED)


def f(ruta, tam):
    return ImageFont.truetype(ruta, tam)


def persona():
    return f"{rng.choice(NOMBRES)}", f"{rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}"


def fecha_es(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def degradar(img: Image.Image, tipo: str) -> Image.Image:
    img = img.convert("L")
    if tipo == "escaner":
        img = img.filter(ImageFilter.GaussianBlur(0.8))
        a = np.array(img, dtype=np.float32) + nprng.normal(0, 10, (img.height, img.width))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    elif tipo == "celular":
        img = img.rotate(rng.uniform(-3.5, 3.5), expand=True, fillcolor=235)
        a = np.array(img, dtype=np.float32)
        grad = np.linspace(0.75, 1.05, a.shape[1])[None, :]
        a = a * grad + nprng.normal(0, 6, a.shape)
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
    nom, ape = persona()
    num = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(2)) + f"{rng.randint(1000000, 9999999)}"
    nac = date(rng.randint(1960, 2004), rng.randint(1, 12), rng.randint(1, 28))
    vencido = rng.random() < 0.2
    ven = FECHA_PRESENTACION + timedelta(days=rng.randint(-900, -30) if vencido else rng.randint(200, 3000))
    sexo = rng.choice("FM")
    personal = "" if rng.random() < 0.5 else f"{rng.randint(10**8, 10**9 - 1)}"
    l1, l2 = generar_td3(pais, ape, nom, num, pais, nac, sexo, ven, personal)
    declarado = f"{nom} {ape}"
    nombre_distinto = rng.random() < 0.1
    if nombre_distinto:
        n2, a2 = persona(); declarado = f"{n2} {a2}"
    img = Image.new("RGB", (1240, 820), "white"); d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 1230, 810], outline="black", width=3)
    d.text((40, 30), f"{nombre_pais} — PASAPORTE / PASSPORT", font=f(FONT_B, 34), fill="black")
    d.text((40, 80), "ESPÉCIMEN FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 22), fill=(150, 0, 0))
    d.rectangle([40, 130, 300, 470], outline="gray", width=2); d.text((110, 290), "FOTO", font=f(FONT, 28), fill="gray")
    y = 135
    for et, v in [("Apellidos / Surname", ape.upper()), ("Nombres / Given names", nom.upper()),
                  ("Nacionalidad / Nationality", nombre_pais), ("Fecha de nacimiento", fecha_es(nac)),
                  ("Sexo / Sex", sexo), ("Fecha de vencimiento", fecha_es(ven)), ("N.º de pasaporte", num)]:
        d.text((330, y), et, font=f(FONT, 18), fill="gray"); d.text((330, y + 20), v, font=f(FONT_B, 24), fill="black"); y += 48
    d.text((40, 660), l1, font=f(MONO, 25), fill="black")
    d.text((40, 710), l2, font=f(MONO, 25), fill="black")
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"pas_{pais}_{i:03d}")
    esperados = []
    if vencido:
        esperados.append("VENCIDO_CON_EXCEPCION" if pais == "VEN" else "PASAPORTE_VENCIDO")
    if nombre_distinto:
        esperados.append("NOMBRE_NO_COINCIDE")
    return {"id": f"pas_{pais}_{i:03d}", "tipo": "pasaporte", "pais": pais, "idioma": idioma, "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": declarado, "numero_pasaporte_declarado": num},
            "verdad": {"numero": num, "apellidos": ape, "nombres": nom, "vencimiento": ven.isoformat(),
                       "mrz1": l1, "mrz2": l2}, "esperados": esperados}


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
    nom, ape = persona(); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FECHA_PRESENTACION - timedelta(days=rng.randint(70, 300) if antiguo else rng.randint(3, 55))
    sin_apostilla = rng.random() < 0.15
    nombre_distinto = rng.random() < 0.1
    declarado = nombre
    if nombre_distinto:
        n2, a2 = persona(); declarado = f"{n2} {a2}"
    doc, folio = f"{rng.randint(10**6, 10**8)}", f"{rng.randint(10**5, 10**7)}"
    img = Image.new("RGB", (1240, 1100), "white"); d = ImageDraw.Draw(img)
    d.text((60, 40), nombre_pais, font=f(FONT_B, 30), fill="black")
    d.text((60, 90), t["tit"], font=f(FONT_B, 32), fill="black")
    d.text((60, 140), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 20), fill=(150, 0, 0))
    y = 210
    for linea in t["cuerpo"]:
        d.text((60, y), linea, font=f(FONT, 24), fill="black"); y += 36
    y += 30
    for et, v in [(t["nom"], nombre), (t["doc"], doc), (t["fec"], fecha_es(emision)), (t["fol"], folio)]:
        d.text((60, y), f"{et}: {v}", font=f(FONT, 26), fill="black"); y += 50
    if not sin_apostilla:
        d.rectangle([640, 760, 1180, 1050], outline="black", width=2)
        d.text((660, 775), "APOSTILLE", font=f(FONT_B, 28), fill="black")
        d.text((660, 815), "(Convention de La Haye du 5 octobre 1961)", font=f(FONT, 17), fill="black")
        d.text((660, 850), f"País: {nombre_pais}", font=f(FONT, 18), fill="black")
        d.text((660, 880), f"N.º {rng.randint(10**5, 10**6)}  Fecha: {fecha_es(emision)}", font=f(FONT, 18), fill="black")
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"ant_{pais}_{i:03d}")
    esperados = (["ANTECEDENTES_ANTIGUO"] if antiguo else []) + (["SIN_APOSTILLA"] if sin_apostilla else []) \
        + (["NOMBRE_NO_COINCIDE"] if nombre_distinto else [])
    return {"id": f"ant_{pais}_{i:03d}", "tipo": "antecedentes_extranjero", "pais": pais, "idioma": idioma,
            "degradacion": deg, "imagen": ruta, "ctx": {"nombre_declarado": declarado},
            "verdad": {"nombre": nombre, "documento": doc, "fecha_emision": emision.isoformat(), "folio": folio},
            "esperados": esperados}


# ---------------------------------------------------- liquidaciones (privado)
def crear_cas(dir_: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    def nombre(cn):
        return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    ahora = datetime.now(timezone.utc)
    out = {}
    for etiqueta, cn in [("acreditada", "Prestador Acreditado de PRUEBA"), ("no_acreditada", "CA No Acreditada de PRUEBA")]:
        kr = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        raiz = (x509.CertificateBuilder().subject_name(nombre(cn)).issuer_name(nombre(cn)).public_key(kr.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
                .not_valid_after(ahora + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
                .sign(kr, hashes.SHA256()))
        kh = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        hoja = (x509.CertificateBuilder().subject_name(nombre(f"Empleador Ficticio ({etiqueta})")).issuer_name(raiz.subject)
                .public_key(kh.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=365))
                .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
                .sign(kr, hashes.SHA256()))
        (dir_ / f"raiz_{etiqueta}.pem").write_bytes(raiz.public_bytes(serialization.Encoding.PEM))
        (dir_ / f"hoja_{etiqueta}.pem").write_bytes(hoja.public_bytes(serialization.Encoding.PEM))
        (dir_ / f"clave_{etiqueta}.pem").write_bytes(kh.private_bytes(serialization.Encoding.PEM,
                                                                      serialization.PrivateFormat.PKCS8,
                                                                      serialization.NoEncryption()))
        out[etiqueta] = dir_
    return out


def pdf_liquidacion(lineas: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf, pageCompression=0)
    y = 780
    for l in lineas:
        c.drawString(60, y, l); y -= 22
    c.save(); return buf.getvalue()


def firmar(pdf: bytes, etiqueta: str, dir_: Path) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    s = signers.SimpleSigner.load(str(dir_ / f"clave_{etiqueta}.pem"), str(dir_ / f"hoja_{etiqueta}.pem"),
                                  ca_chain_files=(str(dir_ / f"raiz_{etiqueta}.pem"),))
    w = IncrementalPdfFileWriter(io.BytesIO(pdf))
    out = signers.sign_pdf(w, signers.PdfSignatureMetadata(field_name="FirmaEmpleador"), signer=s)
    return out.getvalue()


def liquidacion(i: int, dir_ca: Path) -> dict:
    nom, ape = persona(); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FECHA_PRESENTACION - timedelta(days=rng.randint(40, 120) if antiguo else rng.randint(2, 25))
    rut = f"{rng.randint(76, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.choice('0123456789K')}"
    liquido = f"$ {rng.randint(500, 2500)}.{rng.randint(100, 999)}"
    periodo = (emision.replace(day=1) - timedelta(days=1)).strftime("%m/%Y")
    lineas = ["LIQUIDACIÓN DE REMUNERACIONES", "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ",
              f"RUT empleador: {rut}", f"Trabajador: {nombre}", f"Período: {periodo}",
              f"Fecha de emisión: {fecha_es(emision)}", f"Líquido a pagar: {liquido}"]
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img); y = 60
    for k, l in enumerate(lineas):
        d.text((60, y), l, font=f(FONT_B if k == 0 else FONT, 30 if k == 0 else 26),
               fill=(150, 0, 0) if k == 1 else "black"); y += 60
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"liq_{i:03d}")
    # Variantes de firma: 0 acreditada, 1 alterada tras firmar, 2 no acreditada, 3 sin firma.
    variante = i % 4
    pdf = pdf_liquidacion([l.encode("latin-1", "replace").decode("latin-1") for l in lineas])
    esperados = []
    if variante in (0, 1):
        pdf = firmar(pdf, "acreditada", dir_ca)
    elif variante == 2:
        pdf = firmar(pdf, "no_acreditada", dir_ca)
    if variante == 1:
        # Altera el monto dentro del contenido firmado (sin firmar de nuevo).
        idx = pdf.find(b"pagar: $ ")
        pdf = pdf[:idx + 9] + (b"9" if pdf[idx + 9:idx + 10] != b"9" else b"8") + pdf[idx + 10:]
        esperados.append("FIRMA_INVALIDA")
    if variante == 2:
        esperados.append("FIRMANTE_NO_ACREDITADO")
    if variante == 3:
        esperados.append("SIN_FEA")
    if antiguo:
        esperados.append("DOCUMENTO_ANTIGUO")
    p = RAIZ / "pdf" / f"liq_{i:03d}.pdf"; p.write_bytes(pdf)
    return {"id": f"liq_{i:03d}", "tipo": "liquidacion", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "pdf": str(p.relative_to(RAIZ)), "ctx": {"nombre_declarado": nombre},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "rut_empleador": rut,
                       "liquido": liquido, "periodo": periodo},
            "esperados": esperados}


# ------------------------------------------- certificados públicos con QR
def certificado_cl(i: int, registro: dict) -> dict:
    nom, ape = persona(); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.15
    emision = FECHA_PRESENTACION - timedelta(days=rng.randint(70, 200) if antiguo else rng.randint(1, 50))
    folio, codigo = f"{500000 + i}", f"{rng.randint(10**7, 10**8):x}"
    caso = rng.random()
    esperados = []
    if caso < 0.15:          # el código pertenece a otra persona (como en CS Rol 6.236-2025)
        n2, a2 = persona(); registro[folio] = {"codigo": codigo, "titular": f"{n2} {a2}", "fecha_emision": emision.isoformat()}
        esperados.append("CODIGO_DE_OTRA_PERSONA")
    elif caso < 0.25:        # código inexistente en el emisor
        esperados.append("CODIGO_INEXISTENTE")
    else:
        registro[folio] = {"codigo": codigo, "titular": nombre, "fecha_emision": emision.isoformat()}
    if antiguo and "CODIGO_INEXISTENTE" not in esperados:
        esperados.append("DOCUMENTO_ANTIGUO")
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img)
    d.text((60, 50), "CERTIFICADO DE NACIMIENTO (FICTICIO)", font=f(FONT_B, 30), fill="black")
    d.text((60, 100), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=f(FONT, 20), fill=(150, 0, 0))
    y = 180
    for l in [f"Nombre: {nombre}", f"Fecha de emisión: {fecha_es(emision)}", f"Folio: {folio}"]:
        d.text((60, y), l, font=f(FONT, 26), fill="black"); y += 50
    qr = qrcode.make(f"https://verificacion.ejemplo.cl/v?folio={folio}&codigo={codigo}").resize((260, 260))
    img.paste(qr, (900, 560))
    deg = DEGRADACIONES[i % 4]
    ruta = guardar(degradar(img, deg), f"cl_{i:03d}")
    return {"id": f"cl_{i:03d}", "tipo": "certificado_publico_cl", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": nombre},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "folio": folio},
            "esperados": esperados}


def no_soportado(i: int) -> dict:
    img = Image.new("RGB", (1240, 700), "white"); d = ImageDraw.Draw(img)
    for k, l in enumerate(["SÈTIFIKA (DOKIMAN FIKTIF POU TÈS)", "Non: ...", "Dat: ..."]):
        d.text((60, 60 + 60 * k), l, font=f(FONT, 28), fill="black")
    ruta = guardar(img.convert("L"), f"ht_{i:03d}")
    return {"id": f"ht_{i:03d}", "tipo": "antecedentes_extranjero", "pais": "HTI", "idioma": "ht",
            "degradacion": "limpio", "imagen": ruta, "ctx": {"nombre_declarado": "Persona Ficticia"},
            "verdad": {}, "esperados": ["IDIOMA_NO_SOPORTADO"]}


def main():
    for sub in ("imagenes", "pdf", "certs"):
        (RAIZ / sub).mkdir(parents=True, exist_ok=True)
    dir_ca = RAIZ / "certs"; crear_cas(dir_ca)
    docs, registro = [], {}
    for pais in PAISES:
        for i in range(24):
            docs.append(pasaporte(i, pais))
            docs.append(antecedentes(i, pais))
    for i in range(40):
        docs.append(liquidacion(i, dir_ca))
        docs.append(certificado_cl(i, registro))
    for i in range(10):
        docs.append(no_soportado(i))
    (RAIZ / "emisor_simulado.json").write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"fecha_presentacion": FECHA_PRESENTACION.isoformat(), "semilla": SEED, "documentos": docs}
    (RAIZ / "verdad.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(docs)} documentos generados en {RAIZ}")


if __name__ == "__main__":
    main()
