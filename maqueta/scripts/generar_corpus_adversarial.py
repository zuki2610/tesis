"""Corpus adversarial (prueba de robustez ante cambio de distribución).

Se escribió DESPUÉS de congelar el código evaluado (etiqueta git `congelado-evaluacion`)
y no se usó para ajustar el sistema. Introduce, a propósito, condiciones que el
generador de desarrollo no contiene:

- Diagramaciones nuevas: etiqueta y valor en líneas separadas, dos columnas, etiquetas no
  previstas ("Titular", "Expedido el", "Fait à ..., le ...", "Empleador RUT"), y trampas
  como "Nombre del padre:" antes del nombre del titular.
- Fechas con año de dos dígitos, coma o mes antes del día.
- Fuentes distintas (Liberation, FreeSerif, Carlito), fondos con tramas, marcas de agua,
  timbres superpuestos y firmas manuscritas simuladas.
- Fotografías de pasaportes con márgenes (el documento no ocupa toda la imagen), nombres
  largos que se truncan en la MRZ, mayor inclinación, sombras y fotocopias.
- Apostillas en español, e-Apostillas y legalizaciones con otra redacción.
- Códigos QR pequeños o rotados; liquidaciones con otra plantilla y PDF a dos columnas.

Uso: CORPUS_DIR=corpus_ADV SEED=20261023 python scripts/generar_corpus_adversarial.py
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prevalida.mrz import generar_td3  # noqa: E402
import generar_corpus as g  # noqa: E402  (reutiliza nombres, PKI y firma; no la diagramación)

RAIZ = Path(os.environ.get("CORPUS_DIR", Path(__file__).resolve().parent.parent / "corpus_ADV"))
g.RAIZ = RAIZ
SEED = int(os.environ.get("SEED", "20261023"))
rng = random.Random(SEED)
nprng = np.random.default_rng(SEED)
g.rng, g.nprng = rng, nprng
FP = g.FECHA_PRESENTACION

FUENTES = ["/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
           "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
           "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"]
NEGRITA = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
OCRB = g.OCRB
DEG_ADV = ["limpio", "celular_fuerte", "fotocopia", "sombra"]


def fnt(tam, ruta=None):
    return ImageFont.truetype(ruta or rng.choice(FUENTES), tam)


# --------------------------------------------------------------- texturas
def trama(img: Image.Image, intensidad=225):
    d = ImageDraw.Draw(img)
    w, h = img.size
    fase = rng.uniform(0, 6)
    for k in range(0, h, 9):
        pts = [(x, k + 4 * math.sin(x / 37 + fase + k / 50)) for x in range(0, w, 8)]
        d.line(pts, fill=(intensidad,) * 3, width=1)


def marca_agua(img: Image.Image, texto: str):
    capa = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(capa)
    d.text((img.width * 0.15, img.height * 0.4), texto, font=fnt(70, NEGRITA), fill=40)
    capa = capa.rotate(25, expand=False)
    gris = Image.new("RGB", img.size, (205, 205, 205))
    img.paste(gris, (0, 0), capa)


def timbre(img: Image.Image, x, y, texto="TIMBRE"):
    d = ImageDraw.Draw(img)
    r = rng.randint(70, 95)
    d.ellipse([x - r, y - r, x + r, y + r], outline=(90, 90, 150), width=4)
    d.ellipse([x - r + 12, y - r + 12, x + r - 12, y + r - 12], outline=(90, 90, 150), width=2)
    d.text((x - r + 22, y - 10), texto, font=fnt(18, NEGRITA), fill=(90, 90, 150))


def firma_manuscrita(img: Image.Image, x, y):
    d = ImageDraw.Draw(img)
    pts, px, py = [], x, y
    for _ in range(40):
        px += rng.randint(3, 9); py += rng.randint(-12, 12)
        pts.append((px, py))
    d.line(pts, fill=(30, 30, 80), width=3)


def degradar(img: Image.Image, tipo: str) -> Image.Image:
    img = img.convert("L")
    if tipo == "celular_fuerte":
        img = img.rotate(rng.uniform(-6, 6), expand=True, fillcolor=200)
        a = np.array(img, dtype=np.float32)
        a = a * np.linspace(0.6, 1.05, a.shape[1])[None, :] * np.linspace(0.85, 1.0, a.shape[0])[:, None]
        a += nprng.normal(0, 9, a.shape)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9))
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=30); img = Image.open(buf).convert("L")
    elif tipo == "fotocopia":
        a = np.array(img, dtype=np.float32)
        a = np.where(a < 150, 0, 255) + nprng.normal(0, 25, a.shape) * (nprng.random(a.shape) < 0.02)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    elif tipo == "sombra":
        a = np.array(img, dtype=np.float32)
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        a = a * (0.55 + 0.45 * np.clip((xx + yy) / (a.shape[0] + a.shape[1]) * 1.6, 0, 1))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return img


def guardar(img: Image.Image, nombre: str) -> str:
    p = RAIZ / "imagenes" / f"{nombre}.png"
    img.save(p)
    return str(p.relative_to(RAIZ))


def fecha_adv(d: date, idioma: str) -> str:
    """Formatos no presentes en el corpus de desarrollo (y algunos sí)."""
    if idioma == "fr":
        return rng.choice([f"le {d.day} {g.MESES_FR[d.month - 1]} {d.year}", d.strftime("%d/%m/%y"),
                           d.strftime("%d/%m/%Y"), d.strftime("%Y-%m-%d")])
    return rng.choice([f"{d.day} de {g.MESES_ES[d.month - 1]}, {d.year}", d.strftime("%d/%m/%y"),
                       f"{g.MESES_ES[d.month - 1].capitalize()} {d.day} de {d.year}", d.strftime("%Y/%m/%d"),
                       d.strftime("%d/%m/%Y")])


# ----------------------------------------------------------------- pasaportes
def persona_larga(pais):
    nombres, apellidos = g.NOMBRES[pais]
    n = " ".join(rng.sample(nombres, 2))
    return n, " ".join(rng.sample(apellidos, 2))


def pasaporte(i: int, pais: str) -> dict:
    idioma, nombre_pais = g.PAISES[pais]
    nom, ape = persona_larga(pais) if rng.random() < 0.2 else g.persona(pais)
    num = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(9))
    nac = date(rng.randint(1958, 2005), rng.randint(1, 12), rng.randint(1, 28))
    vencido = rng.random() < 0.2
    ven = FP + timedelta(days=rng.randint(-1200, -1) if vencido else rng.randint(1, 3500))
    sexo = rng.choice("FMX") if rng.random() < 0.1 else rng.choice("FM")
    personal = "" if rng.random() < 0.4 else "".join(rng.choice("0123456789ABC") for _ in range(rng.randint(6, 14)))
    l1, l2 = generar_td3(pais, ape, nom, num, pais, nac, sexo, ven, personal)
    declarado, esperados = g.variante_nombre(f"{nom} {ape}", pais)
    W, H = 1300, 900
    doc = Image.new("RGB", (W, H), (248, 246, 240)); trama(doc, 228)
    d = ImageDraw.Draw(doc)
    d.rounded_rectangle([8, 8, W - 8, H - 8], 20, outline=(60, 60, 60), width=3)
    d.text((40, 25), f"REPÚBLICA DE {nombre_pais} · PASSPORT · PASSEPORT", font=fnt(30, NEGRITA), fill="black")
    d.text((40, 70), "Espécimen ficticio para pruebas — sin validez", font=fnt(20), fill=(120, 0, 0))
    d.rectangle([40, 120, 320, 480], fill=(215, 215, 215))
    y = 120
    f_et, f_val = fnt(17), fnt(25)
    for et, v in [("Tipo/Type  Código/Code", f"P   {pais}"), ("Apellidos/Surname", ape.upper()),
                  ("Nombres/Given names", nom.upper()), ("Fecha de nacimiento/Date of birth", nac.strftime("%d %b %Y").upper()),
                  ("Fecha de expiración/Date of expiry", ven.strftime("%d %b %Y").upper()), ("Pasaporte N°", num)]:
        d.text((350, y), et, font=f_et, fill=(90, 90, 90)); d.text((350, y + 20), v, font=f_val, fill="black")
        y += 55
    firma_manuscrita(doc, 360, 480)
    d.rectangle([20, 700, W - 20, 860], fill=(240, 240, 240))
    d.text((40, 720), l1, font=ImageFont.truetype(OCRB, 27), fill="black")
    d.text((40, 780), l2, font=ImageFont.truetype(OCRB, 27), fill="black")
    timbre(doc, rng.randint(600, 1100), rng.randint(200, 450), "MIGRACIÓN")
    con_margen = rng.random() < 0.25
    if con_margen:  # fotografía del pasaporte sobre una mesa
        lienzo = Image.new("RGB", (int(W * 1.45), int(H * 1.6)), (120, 110, 100))
        lienzo.paste(doc, (int(W * 0.2), int(H * 0.25)))
        doc = lienzo
    deg = DEG_ADV[i % 4]
    ruta = guardar(degradar(doc, deg), f"pas_{pais}_{i:03d}")
    if vencido:
        esperados = esperados + ["PASAPORTE_VENCIDO"]
    return {"id": f"pas_{pais}_{i:03d}", "tipo": "pasaporte", "pais": pais, "idioma": idioma, "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": declarado, "numero_pasaporte_declarado": num},
            "verdad": {"numero": num, "apellidos": ape, "nombres": nom, "vencimiento": ven.isoformat(), "mrz1": l1,
                       "mrz2": l2, "nombre_truncado": l1[43] != "<", "con_margen": con_margen},
            "condiciones": ["con_margen"] * con_margen + ["nombre_truncado"] * (l1[43] != "<"),
            "esperados": esperados}


# ------------------------------------------------------------- antecedentes
PLANTILLAS_ES = ["etiqueta_misma_linea", "etiqueta_linea_aparte", "titular_expedido", "trampa_padre", "lugar_y_fecha"]
PLANTILLAS_FR = ["etiqueta_misma_linea", "nom_prenom_separados", "fait_a", "etiqueta_linea_aparte"]


def antecedentes(i: int, pais: str) -> dict:
    idioma, nombre_pais = g.PAISES[pais]
    nom, ape = g.persona(pais); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FP - timedelta(days=g.antiguedad(60, antiguo))
    sin_aut = rng.random() < 0.15
    declarado, esperados = g.variante_nombre(nombre, pais)
    plantilla = rng.choice(PLANTILLAS_FR if idioma == "fr" else PLANTILLAS_ES)
    ftxt = fecha_adv(emision, idioma)
    padre = " ".join(g.persona(pais))
    W, H = 1240, 1500
    img = Image.new("RGB", (W, H), "white")
    if rng.random() < 0.5:
        trama(img, 238)
    if rng.random() < 0.5:
        marca_agua(img, nombre_pais)
    d = ImageDraw.Draw(img)
    fb, fv = fnt(30, NEGRITA), fnt(25)
    d.text((70, 50), f"REPÚBLICA DE {nombre_pais}" if idioma == "es" else f"RÉPUBLIQUE D'{nombre_pais}", font=fb, fill="black")
    d.text((70, 100), "Ministerio de Justicia" if idioma == "es" else "Ministère de la Justice et de la Sécurité Publique",
           font=fv, fill="black")
    d.text((70, 160), "CERTIFICADO DE ANTECEDENTES" if idioma == "es" else "EXTRAIT DE CASIER JUDICIAIRE",
           font=fnt(34, NEGRITA), fill="black")
    d.text((70, 215), "Documento ficticio para pruebas — sin validez", font=fnt(19), fill=(130, 0, 0))
    y = 290
    lineas = []
    if idioma == "es":
        if plantilla == "etiqueta_misma_linea":
            lineas = [("Nombre completo: " + nombre,), ("Documento de identidad: " + str(rng.randint(10**6, 10**8)),),
                      ("Fecha de emisión: " + ftxt,)]
        elif plantilla == "etiqueta_linea_aparte":
            lineas = [("NOMBRE",), (nombre.upper(),), ("FECHA DE EMISIÓN",), (ftxt,)]
        elif plantilla == "titular_expedido":
            lineas = [("Titular: " + nombre,), ("Expedido el: " + ftxt,)]
        elif plantilla == "trampa_padre":
            lineas = [("Nombre del padre: " + padre,), ("Nombre: " + nombre,), ("Fecha de emisión: " + ftxt,)]
        else:
            lineas = [("Apellidos y nombres: " + nombre,), ("Lugar y fecha: Ciudad, " + ftxt,)]
        lineas += [("Se certifica que la persona no registra antecedentes penales.",)]
    else:
        prenoms, noms = nom, ape
        if plantilla == "etiqueta_misma_linea":
            lineas = [("Nom et prénoms : " + nombre,), ("Date de délivrance : " + ftxt,)]
        elif plantilla == "nom_prenom_separados":
            lineas = [("Nom : " + noms.upper(),), ("Prénom(s) : " + prenoms,), ("Date de délivrance : " + ftxt,)]
        elif plantilla == "fait_a":
            lineas = [("Nom et prénoms : " + nombre,), (f"Fait à Port-au-Prince, {ftxt}",)]
        else:
            lineas = [("NOM ET PRÉNOMS",), (nombre.upper(),), ("DATE DE DÉLIVRANCE",), (ftxt,)]
        lineas += [("Néant. Aucune condamnation n'a été prononcée.",)]
    for (l,) in lineas:
        d.text((70, y), l, font=fv, fill="black"); y += 55
    firma_manuscrita(img, 120, y + 60)
    if not sin_aut:
        x0, y0 = 600, 950
        d.rectangle([x0, y0, x0 + 560, y0 + 380], outline=(40, 40, 40), width=2)
        if pais == "HTI":
            for k, t in enumerate(["Vu pour légalisation de la signature", "Ministère des Affaires Étrangères",
                                   "et des Cultes — Port-au-Prince", "Légalisé par le Consulat du Chili"]):
                d.text((x0 + 18, y0 + 20 + 45 * k), t, font=fnt(21), fill="black")
        elif rng.random() < 0.5:
            for k, t in enumerate(["APOSTILLA", "(Convención de La Haya del 5 de octubre de 1961)",
                                   f"1. País: {nombre_pais}", "Apostillado electrónicamente"]):
                d.text((x0 + 18, y0 + 20 + 45 * k), t, font=fnt(24 if k == 0 else 19, NEGRITA if k == 0 else None),
                       fill="black")
            img.paste(qrcode.make(f"https://apostilla.ejemplo/{rng.randint(10**6, 10**7)}").resize((140, 140)),
                      (x0 + 400, y0 + 220))
        else:
            for k, t in enumerate(["APOSTILLE", "(Convention de La Haye du 5 octobre 1961)", f"1. País: {nombre_pais}"]):
                d.text((x0 + 18, y0 + 20 + 45 * k), t, font=fnt(24 if k == 0 else 19), fill="black")
        timbre(img, x0 + 430, y0 + 120, "SELLO")
    deg = DEG_ADV[i % 4]
    ruta = guardar(degradar(img, deg), f"ant_{pais}_{i:03d}")
    esperados = esperados + (["DOCUMENTO_ANTIGUO"] if antiguo else []) + \
        ([("SIN_LEGALIZACION" if pais == "HTI" else "SIN_APOSTILLA")] if sin_aut else [])
    return {"id": f"ant_{pais}_{i:03d}", "tipo": "antecedentes_extranjero", "pais": pais, "idioma": idioma,
            "degradacion": deg, "imagen": ruta, "ctx": {"nombre_declarado": declarado},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "dias": (FP - emision).days},
            "condiciones": [plantilla, "fecha:" + ftxt], "esperados": esperados}


# ---------------------------------------------------------- liquidaciones
def pdf_dos_columnas(pares: list[tuple[str, str]], titulo: str) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf, pageCompression=0)
    c.setFont("Times-Bold", 14); c.drawString(60, 790, titulo)
    y = 750
    for et, v in pares:
        c.setFont("Times-Roman", 11); c.drawString(60, y, et); c.drawString(300, y, v); y -= 20
    c.save(); return buf.getvalue()


def liquidacion(i: int, variante: str, empleadores: list[str], dir_ca: Path) -> dict:
    pais = rng.choice(list(g.PAISES))
    nom, ape = g.persona(pais); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.2
    emision = FP - timedelta(days=g.antiguedad(30, antiguo))
    idx = rng.randrange(len(empleadores)); rut = empleadores[idx]
    plantilla = "conocida" if i % 2 == 0 else "nueva"
    ftxt = fecha_adv(emision, "es")
    if plantilla == "conocida":
        pares = [("RUT empleador:", rut), ("Trabajador:", nombre), ("Fecha de emisión:", ftxt),
                 ("Líquido a pagar:", f"$ {rng.randint(500, 2500)}.{rng.randint(100, 999)}")]
    else:
        pares = [("Empleador RUT", rut), ("Nombre trabajador", nombre), ("Fecha", ftxt),
                 ("Total líquido", f"$ {rng.randint(500, 2500)}.{rng.randint(100, 999)}")]
    titulo = "COMPROBANTE DE REMUNERACIONES (FICTICIO)"
    W, H = 1240, 820
    img = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(img)
    d.text((60, 40), titulo, font=fnt(30, NEGRITA), fill="black")
    y = 140
    for et, v in pares:
        d.text((60, y), et, font=fnt(25), fill="black"); d.text((560, y), v, font=fnt(25), fill="black"); y += 60
    timbre(img, 1000, 600, "PAGADO")
    deg = DEG_ADV[i % 4]
    ruta = guardar(degradar(img, deg), f"liq_{i:03d}")
    pdf = pdf_dos_columnas(pares, titulo)
    if variante in ("valida", "alterada", "incremental"):
        pdf = g.firmar(pdf, idx, dir_ca)
    elif variante == "no_acreditada":
        pdf = g.firmar(pdf, len(empleadores), dir_ca)
    elif variante == "otro_firmante":
        pdf = g.firmar(pdf, (idx + 1) % len(empleadores), dir_ca)
    if variante == "alterada":
        p = pdf.find(b"$ ")
        pdf = pdf[:p + 2] + (b"9" if pdf[p + 2:p + 3] != b"9" else b"8") + pdf[p + 3:]
    if variante == "incremental":
        pdf = g.agregar_incremental(pdf, "Total corregido: $ 9.999.999")
    p = RAIZ / "pdf" / f"liq_{i:03d}.pdf"; p.write_bytes(pdf)
    esperados = list(g.ESPERADO_FIRMA[variante]) + (["DOCUMENTO_ANTIGUO"] if antiguo else [])
    return {"id": f"liq_{i:03d}", "tipo": "liquidacion", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "pdf": str(p.relative_to(RAIZ)), "variante_firma": variante,
            "ctx": {"nombre_declarado": nombre},
            "verdad": {"nombre": nombre, "fecha_emision": emision.isoformat(), "rut_empleador": rut,
                       "dias": (FP - emision).days},
            "condiciones": ["plantilla_" + plantilla, "fecha:" + ftxt], "esperados": esperados}


# ------------------------------------------------------- certificados con QR
def certificado_cl(i: int, registro: dict) -> dict:
    nom, ape = g.persona(rng.choice(list(g.PAISES))); nombre = f"{nom} {ape}"
    antiguo = rng.random() < 0.15
    emision = FP - timedelta(days=g.antiguedad(60, antiguo))
    folio, codigo = f"{700000 + i}", f"{rng.randint(10**7, 10**8):x}"
    caso = rng.random(); esperados = []; titular = nombre
    if caso < 0.12:
        titular = g.persona_distinta(rng.choice(list(g.PAISES)), nombre); esperados.append("CODIGO_DE_OTRA_PERSONA")
    elif caso < 0.18:
        titular = g.nombre_casi(nombre); esperados.append("NOMBRE_CASI_COINCIDE")
    if 0.18 <= caso < 0.28:
        esperados.append("CODIGO_INEXISTENTE")
    else:
        registro[folio] = {"codigo": codigo, "titular": titular, "fecha_emision": emision.isoformat()}
    if antiguo and "CODIGO_INEXISTENTE" not in esperados:
        esperados.append("DOCUMENTO_ANTIGUO")
    img = Image.new("RGB", (1240, 1000), "white"); trama(img, 235); d = ImageDraw.Draw(img)
    d.text((60, 50), "CERTIFICADO (FICTICIO)", font=fnt(32, NEGRITA), fill="black")
    d.text((60, 160), f"Titular: {nombre}", font=fnt(26), fill="black")
    tam = rng.choice([110, 140, 200])
    qr = qrcode.make(f"https://verificacion.ejemplo.cl/v?folio={folio}&codigo={codigo}").resize((tam, tam))
    if rng.random() < 0.4:
        qr = qr.convert("L").rotate(rng.choice([90, 180, 270, rng.uniform(-15, 15)]), expand=True, fillcolor=255)
    img.paste(qr, (rng.randint(700, 1240 - qr.width - 20), rng.randint(600, 1000 - qr.height - 20)))
    timbre(img, 300, 700, "REGISTRO")
    deg = DEG_ADV[i % 4]
    ruta = guardar(degradar(img, deg), f"cl_{i:03d}")
    return {"id": f"cl_{i:03d}", "tipo": "certificado_publico_cl", "pais": "CHL", "idioma": "es", "degradacion": deg,
            "imagen": ruta, "ctx": {"nombre_declarado": nombre}, "verdad": {"nombre": nombre},
            "condiciones": [f"qr_{tam}px"], "esperados": esperados}


def criollo(i: int) -> dict:
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img)
    for k, l in enumerate(["REPIBLIK DAYITI", "SÈTIFIKA DOSYE JIDISYÈ (FIKTIF)", "Moun nan: Nadège Toussaint",
                           "Bay nan dat: 12 out 2026", "Pa gen okenn kondanasyon."]):
        d.text((60, 60 + 70 * k), l, font=fnt(30), fill="black")
    ruta = guardar(degradar(img, DEG_ADV[i % 4]), f"ht_{i:03d}")
    return {"id": f"ht_{i:03d}", "tipo": "antecedentes_extranjero", "pais": "HTI", "idioma": "fr",
            "degradacion": DEG_ADV[i % 4], "imagen": ruta, "ctx": {"nombre_declarado": "Nadège Toussaint"},
            "verdad": {}, "condiciones": ["criollo_declarado_fr"], "esperados": ["DOCUMENTO_NO_RECONOCIDO"]}


def main():
    for sub in ("imagenes", "pdf", "certs"):
        (RAIZ / sub).mkdir(parents=True, exist_ok=True)
    empleadores = [f"{rng.randint(76, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.choice('0123456789K')}"
                   for _ in range(8)]
    dir_ca = RAIZ / "certs"; g.crear_pki(dir_ca, empleadores)
    docs, registro = [], {}
    for pais in g.PAISES:
        for i in range(16):
            docs.append(pasaporte(i, pais))
            docs.append(antecedentes(i, pais))
    variantes = g.VARIANTES_FIRMA * 8; rng.shuffle(variantes)
    for i, v in enumerate(variantes):
        docs.append(liquidacion(i, v, empleadores, dir_ca))
    for i in range(30):
        docs.append(certificado_cl(i, registro))
    for i in range(8):
        docs.append(criollo(i))
    (RAIZ / "emisor_simulado.json").write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"generador": "adversarial", "fecha_presentacion": FP.isoformat(), "semilla": SEED, "documentos": docs}
    (RAIZ / "verdad.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(docs)} documentos adversariales generados en {RAIZ}")


if __name__ == "__main__":
    main()
