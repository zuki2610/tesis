"""Demostración de la maqueta con dos expedientes ficticios.

Genera documentos ficticios para dos personas solicitantes, los carga en la API de la
maqueta (la misma de `prevalida/api.py`, mediante el cliente de pruebas de FastAPI, sin red)
y guarda lo que ve la persona solicitante y lo que ve el funcionario:

  demo/documentos/      imágenes y PDF ficticios cargados
  demo/resultado.json   respuestas de la API
  demo/reporte.html     página para revisar la demostración en el navegador

Todos los documentos llevan la leyenda de documento ficticio, con datos inventados, y no
reproducen el diseño oficial de ningún país. Las fechas se calculan desde el día de ejecución,
porque la API toma ese día como fecha de presentación.

Uso: python scripts/demo_expediente.py        (DEMO_DIR=otra_carpeta cambia la salida)
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEMO = Path(os.environ.get("DEMO_DIR", BASE / "demo")).resolve()
DOCS = DEMO / "documentos"
TRABAJO = DEMO / "_trabajo"
os.environ["CORPUS_DIR"] = str(TRABAJO)  # carpeta del generador (no se usa para guardar documentos)
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

import qrcode  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import generar_corpus as g  # noqa: E402
from prevalida.mrz import generar_td3  # noqa: E402

HOY = date.today()
EMPLEADORES = ["76.543.210-3", "77.120.885-K"]
NOMBRE_PAIS = {"VEN": "VENEZUELA", "PER": "PERÚ", "COL": "COLOMBIA", "BOL": "BOLIVIA", "HTI": "HAÏTI"}


# ------------------------------------------------------------------ documentos ficticios
def img_pasaporte(pais, apellidos, nombres, numero, nacimiento, sexo, vencimiento):
    l1, l2 = generar_td3(pais, apellidos, nombres, numero, pais, nacimiento, sexo, vencimiento)
    img = Image.new("RGB", (1240, 820), "white"); d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 1230, 810], outline="black", width=3)
    d.text((40, 30), f"{NOMBRE_PAIS[pais]} — PASAPORTE / PASSPORT", font=g.f(g.FONT_B, 34), fill="black")
    d.text((40, 80), "ESPÉCIMEN FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=g.f(g.FONT, 22), fill=(150, 0, 0))
    d.rectangle([40, 130, 300, 470], outline="gray", width=2)
    d.text((110, 290), "FOTO", font=g.f(g.FONT, 28), fill="gray")
    y = 135
    for et, v in [("Apellidos / Surname", apellidos.upper()), ("Nombres / Given names", nombres.upper()),
                  ("Nacionalidad / Nationality", NOMBRE_PAIS[pais]),
                  ("Fecha de nacimiento", nacimiento.strftime("%d/%m/%Y")), ("Sexo / Sex", sexo),
                  ("Fecha de vencimiento", vencimiento.strftime("%d/%m/%Y")), ("N.º de pasaporte", numero)]:
        d.text((330, y), et, font=g.f(g.FONT, 18), fill="gray")
        d.text((330, y + 20), v, font=g.f(g.FONT_B, 24), fill="black")
        y += 48
    d.text((40, 660), l1, font=g.f(g.OCRB, 25), fill="black")
    d.text((40, 710), l2, font=g.f(g.OCRB, 25), fill="black")
    return img.convert("L"), [l1, l2]


def img_antecedentes(pais, nombre, emision, autenticado):
    idioma = "fr" if pais == "HTI" else "es"
    t = g.TXT_ANT[idioma]
    img = Image.new("RGB", (1240, 1100), "white"); d = ImageDraw.Draw(img)
    d.text((60, 40), NOMBRE_PAIS[pais], font=g.f(g.FONT_B, 30), fill="black")
    d.text((60, 90), t["tit"], font=g.f(g.FONT_B, 32), fill="black")
    d.text((60, 140), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=g.f(g.FONT, 20), fill=(150, 0, 0))
    y = 210
    for linea in t["cuerpo"]:
        d.text((60, y), linea, font=g.f(g.FONT, 24), fill="black"); y += 36
    y += 30
    for et, v in [(t["nom"], nombre), (t["doc"], "48215573"), (t["fec"], emision.strftime("%d/%m/%Y")),
                  (t["fol"], "3307142")]:
        d.text((60, y), f"{et}: {v}", font=g.f(g.FONT, 26), fill="black"); y += 50
    if autenticado:
        d.rectangle([640, 760, 1180, 1050], outline="black", width=2)
        if pais == "HTI":
            d.text((660, 775), "LÉGALISATION", font=g.f(g.FONT_B, 28), fill="black")
            d.text((660, 815), "Ministère des Affaires Étrangères et des Cultes", font=g.f(g.FONT, 17), fill="black")
            d.text((660, 850), "Consulado de Chile en Puerto Príncipe", font=g.f(g.FONT, 18), fill="black")
        else:
            d.text((660, 775), "APOSTILLE", font=g.f(g.FONT_B, 28), fill="black")
            d.text((660, 815), "(Convention de La Haye du 5 octobre 1961)", font=g.f(g.FONT, 17), fill="black")
            d.text((660, 850), f"País: {NOMBRE_PAIS[pais]}", font=g.f(g.FONT, 18), fill="black")
            d.text((660, 880), "N.º 512094", font=g.f(g.FONT, 18), fill="black")
    return img.convert("L")


def img_certificado_cl(titulo, nombre, emision, folio, codigo):
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img)
    d.text((60, 50), titulo, font=g.f(g.FONT_B, 30), fill="black")
    d.text((60, 100), "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ", font=g.f(g.FONT, 20), fill=(150, 0, 0))
    y = 180
    for linea in [f"Nombre: {nombre}", f"Fecha de emisión: {emision.strftime('%d/%m/%Y')}", f"Folio: {folio}"]:
        d.text((60, y), linea, font=g.f(g.FONT, 26), fill="black"); y += 50
    qr = qrcode.make(f"https://verificacion.ejemplo.cl/v?folio={folio}&codigo={codigo}").resize((260, 260))
    img.paste(qr, (900, 560))
    return img.convert("L")


def img_criollo(nombre):
    img = Image.new("RGB", (1240, 700), "white"); d = ImageDraw.Draw(img)
    for k, linea in enumerate(["SÈTIFIKA DOSYE JIDISYÈ (DOKIMAN FIKTIF POU TÈS)", f"Non konplè: {nombre}",
                               "Dat: 3 out 2026", "Otorite a sètifye moun sa a pa gen okenn kondanasyon."]):
        d.text((60, 60 + 60 * k), linea, font=g.f(g.FONT, 28), fill="black")
    return img.convert("L")


def liquidacion(nombre, emision, idx_empleador, modificar=False):
    lineas = ["LIQUIDACIÓN DE REMUNERACIONES", "DOCUMENTO FICTICIO PARA PRUEBAS — SIN VALIDEZ",
              f"RUT empleador: {EMPLEADORES[idx_empleador]}", f"Trabajador: {nombre}",
              f"Período: {(emision.replace(day=1) - timedelta(days=1)).strftime('%m/%Y')}",
              f"Fecha de emisión: {emision.strftime('%d/%m/%Y')}", "Líquido a pagar: $ 1.284.500"]
    img = Image.new("RGB", (1240, 900), "white"); d = ImageDraw.Draw(img); y = 60
    for k, linea in enumerate(lineas):
        d.text((60, y), linea, font=g.f(g.FONT_B if k == 0 else g.FONT, 30 if k == 0 else 26),
               fill=(150, 0, 0) if k == 1 else "black"); y += 60
    pdf = g.firmar(g.pdf_liquidacion(lineas), idx_empleador, TRABAJO / "certs")
    if modificar:
        pdf = g.agregar_incremental(pdf, "Liquido a pagar corregido: $ 2.900.000")
    return img.convert("L"), pdf


def preparar():
    """Crea los documentos de los dos expedientes y el registro del emisor simulado."""
    for p in (DOCS, TRABAJO):
        shutil.rmtree(p, ignore_errors=True)
    DOCS.mkdir(parents=True); (TRABAJO / "certs").mkdir(parents=True)
    g.crear_pki(TRABAJO / "certs", EMPLEADORES)
    registro = {
        "604211": {"codigo": "a3f91c07", "titular": "María José Rojas Pérez",
                   "fecha_emision": (HOY - timedelta(days=12)).isoformat()},
        "604377": {"codigo": "5be20d94", "titular": "Jean Pierre Dorvil",
                   "fecha_emision": (HOY - timedelta(days=9)).isoformat()},
    }
    (TRABAJO / "emisor.json").write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")

    def doc(archivo, titulo, tipo, idioma, pais, imagen, pdf=None):
        imagen.save(DOCS / f"{archivo}.png")
        if pdf:
            (DOCS / f"{archivo}.pdf").write_bytes(pdf)
        return {"archivo": f"{archivo}.png", "pdf": f"{archivo}.pdf" if pdf else None, "titulo": titulo,
                "tipo": tipo, "idioma": idioma, "pais": pais}

    mj = "María José Rojas Pérez"
    pas_a, mrz_a = img_pasaporte("VEN", "Rojas Pérez", "María José", "VE4821736", date(1988, 4, 12), "F",
                                 HOY + timedelta(days=1460))
    liq_ok = liquidacion(mj, HOY - timedelta(days=8), 0)
    liq_mod = liquidacion(mj, HOY - timedelta(days=8), 0, modificar=True)
    a = {"nombre": mj, "nacionalidad": "Venezuela", "pasaporte": "VE4821736", "paises": ["VEN", "PER", "COL"],
         "descripcion": "Venezolana; en los últimos cinco años residió en Venezuela, Perú y Colombia.",
         "documentos": [
             doc("a1_pasaporte", "Pasaporte venezolano", "pasaporte", "es", "VEN", pas_a),
             doc("a2_antecedentes_ven", "Certificado de antecedentes de Venezuela, apostillado",
                 "antecedentes_extranjero", "es", "VEN", img_antecedentes("VEN", mj, HOY - timedelta(days=20), True)),
             doc("a3_antecedentes_per", "Certificado de antecedentes de Perú, emitido hace 95 días",
                 "antecedentes_extranjero", "es", "PER", img_antecedentes("PER", mj, HOY - timedelta(days=95), True)),
             doc("a4_union_civil", "Certificado chileno de unión civil con código QR", "certificado_publico_cl", "es",
                 "CHL", img_certificado_cl("CERTIFICADO DE UNIÓN CIVIL (FICTICIO)", mj, HOY - timedelta(days=12),
                                           "604211", "a3f91c07")),
             doc("a5_liquidacion", "Liquidación de sueldo con firma electrónica avanzada", "liquidacion", "es", "CHL",
                 *liq_ok),
             doc("a6_liquidacion_modificada", "Liquidación de sueldo modificada después de firmada", "liquidacion",
                 "es", "CHL", *liq_mod),
         ], "mrz": mrz_a}
    pas_b, mrz_b = img_pasaporte("HTI", "Joseph", "Wisly", "HT5039821", date(1992, 7, 3), "M",
                                 HOY + timedelta(days=900))
    b = {"nombre": "Wisly Joseph", "nacionalidad": "Haití", "pasaporte": "HT5039821", "paises": ["HTI"],
         "descripcion": "Haitiano; en los últimos cinco años residió solo en Haití.",
         "documentos": [
             doc("b1_pasaporte", "Pasaporte haitiano", "pasaporte", "fr", "HTI", pas_b),
             doc("b2_casier_judiciaire", "Certificado de antecedentes de Haití, sin legalización consular",
                 "antecedentes_extranjero", "fr", "HTI",
                 img_antecedentes("HTI", "Wisly Joseph", HOY - timedelta(days=15), False)),
             doc("b3_antecedentes_cl", "Certificado chileno con código QR que corresponde a otra persona",
                 "certificado_publico_cl", "es", "CHL",
                 img_certificado_cl("CERTIFICADO DE ANTECEDENTES (FICTICIO)", "Wisly Joseph", HOY - timedelta(days=9),
                                    "604377", "5be20d94")),
             doc("b4_criollo", "Certificado en criollo haitiano", "antecedentes_extranjero", "ht", "HTI",
                 img_criollo("Wisly Joseph")),
         ], "mrz": mrz_b}
    return [a, b]


# ------------------------------------------------------------------ ejecución en la API
def ejecutar(expedientes):
    os.environ["EMISOR_JSON"] = str(TRABAJO / "emisor.json")
    os.environ["RAICES_FEA"] = str(TRABAJO / "certs" / "raiz_acreditada.pem")
    os.environ.setdefault("TESSDATA_DIR", str(BASE / "tessdata"))
    from fastapi.testclient import TestClient
    import prevalida.api as api
    cliente = TestClient(api.app)
    for e in expedientes:
        e["id"] = cliente.post("/solicitudes", data={"nombre": e["nombre"], "numero_pasaporte": e["pasaporte"],
                                                     "paises_residencia": ",".join(e["paises"])}).json()["id"]
        for d in e["documentos"]:
            archivos = {"imagen": (d["archivo"], (DOCS / d["archivo"]).read_bytes(), "image/png")}
            if d["pdf"]:
                archivos["pdf"] = (d["pdf"], (DOCS / d["pdf"]).read_bytes(), "application/pdf")
            t0 = time.perf_counter()
            r = cliente.post(f"/solicitudes/{e['id']}/documentos", files=archivos,
                             data={"tipo": d["tipo"], "idioma": d["idioma"], "pais": d["pais"]})
            r.raise_for_status()
            d["respuesta"], d["segundos"] = r.json(), round(time.perf_counter() - t0, 2)
            print(f"  {d['titulo']}: {d['respuesta']['estado']} {d['respuesta']['mensajes']}", flush=True)
    ancla = cliente.post("/bitacora/ancla").json()
    for e in expedientes:
        vista = cliente.get(f"/solicitudes/{e['id']}").json()
        for d, v in zip(e["documentos"], vista["documentos"]):
            d["funcionario"] = v
        e["controles_expediente"], e["bitacora_integra"] = vista["expediente"], vista["bitacora_integra"]
    filas = api._prev.bitacora.db.execute(
        "SELECT id, ts, solicitud, actor, evento, datos, hash_prev, hash FROM eventos ORDER BY id").fetchall()
    bitacora = [{"n": f[0], "ts": f[1], "solicitud": f[2], "actor": f[3], "evento": f[4],
                 "datos": json.loads(f[5]), "hash_prev": f[6], "hash": f[7]} for f in filas]
    return {"fecha": HOY.isoformat(), "motor": "Tesseract", "expedientes": expedientes, "ancla": ancla,
            "bitacora": bitacora}


# ------------------------------------------------------------------ reporte
ESTADO = {"PREVALIDADO": ("Prevalidado", "ok"), "CON_ALERTAS": ("Con alertas", "alerta"),
          "REVISION_HUMANA": ("Derivado a revisión humana", "derivado")}
VIA = {"emisor": "Emisor", "firma_pdf": "Firma electrónica (texto del PDF firmado)",
       "firma_y_ocr": "Firma electrónica y OCR", "ocr": "OCR y reglas", "ocr_mrz": "OCR de la MRZ",
       "directo_humano": "Directo a revisión humana"}
TIPO_HALLAZGO = {"ALERTA": ("Alerta", "alerta"), "REVISION_HUMANA": ("Revisión humana", "derivado")}
ETIQUETA_CAMPO = {"numero": "N.º de pasaporte", "apellidos": "Apellidos", "nombres": "Nombres",
                  "vencimiento": "Vencimiento", "controles": "Dígitos de control", "confianza": "Confianza",
                  "nombre": "Nombre", "fecha_emision": "Fecha de emisión", "rut_empleador": "RUT empleador",
                  "autenticacion": "Apostilla o legalización", "titular": "Titular según el emisor",
                  "folio": "Folio", "existe": "Existe en el emisor", "qr_leido": "QR leído",
                  "documento": "N.º de documento", "periodo": "Período", "liquido": "Líquido a pagar"}


def miniatura(ruta: Path, ancho=900) -> str:
    im = Image.open(ruta).convert("L")
    if im.width > ancho:
        im = im.resize((ancho, int(im.height * ancho / im.width)))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def e_(x) -> str:
    return html.escape(str(x))


def _fecha(x):
    try:
        return date.fromisoformat(str(x)).strftime("%d/%m/%Y")
    except ValueError:
        return x


def _conf(c) -> str:
    return f"{c:.2f}".replace(".", ",")


def datos_leidos(v: dict) -> str:
    c = v.get("campos") or {}
    filas = []
    for k, val in c.items():
        if k == "firma":
            if val:
                filas += [("Firma", "íntegra" if val.get("integra") else "alterada"),
                          ("Cambios tras firmar", "sí" if val.get("modificado_tras_firma") else "no"),
                          ("Prestador acreditado", "sí" if val.get("confiable") else "no"),
                          ("RUT del firmante", val.get("rut_firmante") or "—")]
            continue
        if k == "controles" and isinstance(val, dict):
            txt = f"{sum(bool(x) for x in val.values())} de {len(val)} válidos"
        elif k == "autenticacion" and isinstance(val, dict):
            hay = [n for n, ok in (("apostilla", val.get("apostilla")), ("legalización", val.get("legalizacion"))) if ok]
            txt = " y ".join(hay) + " detectada" if hay else "no detectada"
        elif isinstance(val, dict):
            txt, conf = val.get("valor"), val.get("confianza")
            txt = "no leído" if txt in (None, "") else f"{txt}" + (f" (confianza {_conf(conf)})" if conf is not None else "")
        elif isinstance(val, bool) or val in ("True", "False"):
            txt = "sí" if val in (True, "True") else "no"
        elif isinstance(val, float):
            txt = _conf(val)
        elif k in ("vencimiento", "fecha_emision"):
            txt = _fecha(val)
        else:
            txt = val
        filas.append((ETIQUETA_CAMPO.get(k, k), txt))
    if not filas:
        return '<p class="muted">El sistema no lee este documento: lo deriva directamente.</p>'
    return "<dl class=\"datos\">" + "".join(f"<dt>{e_(a)}</dt><dd>{e_(b)}</dd>" for a, b in filas) + "</dl>"


def pill(estado: str) -> str:
    t, cls = ESTADO.get(estado, (estado, "derivado"))
    return f'<span class="pill {cls}">{e_(t)}</span>'


def reporte(res: dict, completo: bool) -> str:
    fecha = date.fromisoformat(res["fecha"]).strftime("%d-%m-%Y")
    tabs, paneles = [], []
    for k, e in enumerate(res["expedientes"]):
        sel = k == 0
        tabs.append(f'<button class="exp-tab" role="tab" id="tab-{k}" aria-selected="{str(sel).lower()}" '
                    f'aria-controls="exp-{k}" data-exp="{k}"><span class="exp-nombre">{e_(e["nombre"])}</span>'
                    f'<span class="exp-meta">{e_(e["nacionalidad"])} · {len(e["documentos"])} documentos</span></button>')
        tarjetas = []
        for i, d in enumerate(e["documentos"]):
            r = d["respuesta"]
            msgs = "".join(f"<li>{e_(m)}</li>" for m in r["mensajes"]) or "<li>Sin observaciones.</li>"
            tarjetas.append(f'''<article class="doc">
  <button class="thumb" type="button" data-img="img-{k}-{i}" aria-label="Ampliar {e_(d["titulo"])}"><img id="img-{k}-{i}" src="{miniatura(DOCS / d["archivo"])}" alt="{e_(d["titulo"])} (documento ficticio)"></button>
  <div class="doc-body">
    <h3>{e_(d["titulo"])}</h3>
    <p class="doc-meta">Cargado como <code>{e_(d["tipo"])}</code> · idioma <code>{e_(d["idioma"])}</code>{' · con PDF firmado' if d["pdf"] else ''}</p>
    <div class="respuesta">
      <div class="resp-head">{pill(r["estado"])}<span class="via">{e_(VIA.get(r["via"], r["via"]))}</span></div>
      <ul class="msgs">{msgs}</ul>
      <p class="enviar">Puede enviar la solicitud: <strong>{"sí" if r["puede_enviar"] else "no"}</strong> · respuesta en {str(d["segundos"]).replace(".", ",")} s</p>
    </div>
  </div>
</article>''')
        filas = []
        for d in e["documentos"]:
            v = d["funcionario"]
            hall = "".join(f'<li><span class="tag {TIPO_HALLAZGO[h["tipo"]][1]}">{TIPO_HALLAZGO[h["tipo"]][0]}</span> '
                           f'<code>{e_(h["codigo"])}</code><br>{e_(h["mensaje"])}</li>' for h in v["hallazgos"])
            filas.append(f'<tr><td><strong>{e_(d["titulo"])}</strong><br><span class="muted">{e_(VIA.get(v["via"], v["via"]))}</span></td>'
                         f'<td>{pill(v["estado"])}</td><td>{datos_leidos(v)}</td>'
                         f'<td>{"<ul class=hall>" + hall + "</ul>" if hall else "<span class=muted>Ninguno</span>"}</td></tr>')
        cuenta = {s: sum(d["funcionario"]["estado"] == s for d in e["documentos"]) for s in ESTADO}
        ctrl = "".join(f'<li><span class="tag {TIPO_HALLAZGO[h["tipo"]][1]}">{TIPO_HALLAZGO[h["tipo"]][0]}</span> {e_(h["mensaje"])}</li>'
                       for h in e["controles_expediente"]) or "<li>Hay un certificado de antecedentes por cada país de residencia declarado.</li>"
        eventos = [b for b in res["bitacora"] if b["solicitud"] == e["id"]]
        bit = "".join(f'<tr><td class="num">{b["n"]}</td><td>{e_(b["actor"])}</td><td>{e_(b["evento"])}</td>'
                      f'<td>{e_(b["datos"].get("tipo", b["datos"].get("nombre", "")))}</td>'
                      f'<td>{e_(b["datos"].get("estado", ""))}</td><td><code>{b["hash"][:16]}…</code></td></tr>' for b in eventos)
        paneles.append(f'''<section class="exp" id="exp-{k}" role="tabpanel" aria-labelledby="tab-{k}"{'' if sel else ' hidden'}>
  <div class="ficha">
    <div><span class="lbl">Solicitante</span><strong>{e_(e["nombre"])}</strong></div>
    <div><span class="lbl">Pasaporte declarado</span><code>{e_(e["pasaporte"])}</code></div>
    <div><span class="lbl">Países de residencia (5 años)</span>{e_(", ".join(e["paises"]))}</div>
    <p class="ficha-desc">{e_(e["descripcion"])}</p>
  </div>
  <div class="vista" data-vista="persona">
    <p class="vista-intro">Cada documento recibe una respuesta inmediata. El sistema advierte, pero no rechaza: la persona puede corregir o enviar igual.</p>
    <div class="docs">{"".join(tarjetas)}</div>
  </div>
  <div class="vista" data-vista="funcionario" hidden>
    <div class="resumen">
      <div><span class="big">{cuenta["PREVALIDADO"]}</span><span class="lbl">prevalidados</span></div>
      <div><span class="big">{cuenta["CON_ALERTAS"]}</span><span class="lbl">con alertas</span></div>
      <div><span class="big">{cuenta["REVISION_HUMANA"]}</span><span class="lbl">derivados a revisión</span></div>
    </div>
    <h3 class="sec">Documentos del expediente</h3>
    <div class="tabla-wrap"><table class="tabla">
      <thead><tr><th>Documento y vía</th><th>Estado</th><th>Datos leídos o verificados</th><th>Hallazgos</th></tr></thead>
      <tbody>{"".join(filas)}</tbody></table></div>
    <h3 class="sec">Controles del expediente</h3>
    <ul class="ctrl">{ctrl}</ul>
    <h3 class="sec">Bitácora</h3>
    <p class="muted">Cada evento guarda el hash del anterior. Verificación contra el ancla externa ({res["ancla"]["n"]} eventos): <strong>{"íntegra" if e["bitacora_integra"] else "alterada"}</strong>.</p>
    <div class="tabla-wrap"><table class="tabla bit">
      <thead><tr><th>#</th><th>Actor</th><th>Evento</th><th>Documento</th><th>Estado</th><th>Hash</th></tr></thead>
      <tbody>{bit}</tbody></table></div>
  </div>
</section>''')
    cuerpo = f'''<title>Prevalida en funcionamiento</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Diseño: expediente administrativo; banda institucional arriba, tarjetas de documento y tabla del funcionario */
:root {{
  --bg: #f4f6f9; --surface: #ffffff; --ink: #172235; --muted: #5b6678; --line: #d9dee7;
  --accent: #1f4e8c; --accent-soft: #e6eef8;
  --ok: #1d7a4a; --ok-soft: #e3f3ea; --warn: #9a5b00; --warn-soft: #fbefd9; --ref: #2f5aa8; --ref-soft: #e5ecfa;
  --font-display: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --font-body: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0f1621; --surface: #172131; --ink: #e6ebf3; --muted: #9aa6b8; --line: #2a374b;
  --accent: #8db4ef; --accent-soft: #1d2d45;
  --ok: #6fd19c; --ok-soft: #173327; --warn: #f2bd63; --warn-soft: #3a2c12; --ref: #9bb8f5; --ref-soft: #1d2a47; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #0f1621; --surface: #172131; --ink: #e6ebf3; --muted: #9aa6b8; --line: #2a374b;
  --accent: #8db4ef; --accent-soft: #1d2d45;
  --ok: #6fd19c; --ok-soft: #173327; --warn: #f2bd63; --warn-soft: #3a2c12; --ref: #9bb8f5; --ref-soft: #1d2a47; color-scheme: dark }}
* {{ box-sizing: border-box }}
[hidden] {{ display: none !important }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--font-body); font-size: 15px; line-height: 1.5; margin: 0 }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 28px 56px; display: grid; gap: 24px }}
header.top {{ display: grid; gap: 10px }}
.eyebrow {{ font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); font-weight: 600 }}
h1 {{ font-family: var(--font-display); font-weight: 800; font-size: clamp(28px, 4vw, 40px); line-height: 1.1; margin: 0; text-wrap: balance }}
.lede {{ max-width: 70ch; margin: 0; color: var(--muted) }}
.vias {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px }}
.via-card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; display: grid; gap: 4px }}
.via-card strong {{ font-size: 14px }}
.via-card span {{ color: var(--muted); font-size: 13.5px }}
.controles {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch; justify-content: space-between }}
.exp-tabs {{ display: flex; flex-wrap: wrap; gap: 8px }}
.exp-tab {{ font: inherit; text-align: left; border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 8px; padding: 8px 14px; cursor: pointer; display: grid }}
.exp-tab[aria-selected="true"] {{ border-color: var(--accent); background: var(--accent-soft) }}
.exp-nombre {{ font-weight: 700 }}
.exp-meta {{ font-size: 12.5px; color: var(--muted) }}
.vista-toggle {{ display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: center; background: var(--surface) }}
.vista-toggle button {{ font: inherit; font-weight: 600; border: 0; background: transparent; color: var(--muted); padding: 9px 14px; cursor: pointer }}
.vista-toggle button[aria-pressed="true"] {{ background: var(--accent); color: var(--surface) }}
button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px }}
.exp {{ display: grid; gap: 18px }}
.ficha {{ display: flex; flex-wrap: wrap; gap: 10px 28px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px }}
.ficha > div {{ display: grid }}
.lbl {{ font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 600 }}
.ficha-desc {{ flex-basis: 100%; margin: 0; color: var(--muted) }}
code {{ font-family: var(--font-mono); font-size: .92em }}
.vista-intro {{ margin: 0 0 4px; color: var(--muted); max-width: 72ch }}
.docs {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr)); gap: 14px }}
.doc {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; display: grid; grid-template-rows: auto 1fr; min-width: 0 }}
.thumb {{ border: 0; padding: 0; background: #ffffff; cursor: zoom-in; border-bottom: 1px solid var(--line); display: block; width: 100% }}
.thumb img {{ display: block; width: 100%; height: 190px; object-fit: contain; background: #ffffff }}
.doc-body {{ padding: 12px 14px 14px; display: grid; gap: 8px; align-content: start; min-width: 0 }}
.doc h3 {{ font-size: 15.5px; margin: 0; line-height: 1.3; text-wrap: balance }}
.doc-meta {{ margin: 0; font-size: 12.5px; color: var(--muted) }}
.respuesta {{ border-top: 1px dashed var(--line); padding-top: 10px; display: grid; gap: 6px }}
.resp-head {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center }}
.via {{ font-size: 12.5px; color: var(--muted) }}
.msgs {{ margin: 0; padding-left: 18px }}
.enviar {{ margin: 0; font-size: 12.5px; color: var(--muted) }}
.pill, .tag {{ display: inline-block; border-radius: 999px; font-size: 12px; font-weight: 700; padding: 2px 10px; white-space: nowrap }}
.tag {{ border-radius: 4px; padding: 1px 6px; font-size: 11px; letter-spacing: .02em }}
.ok {{ background: var(--ok-soft); color: var(--ok) }}
.alerta {{ background: var(--warn-soft); color: var(--warn) }}
.derivado {{ background: var(--ref-soft); color: var(--ref) }}
.resumen {{ display: flex; flex-wrap: wrap; gap: 12px }}
.resumen > div {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px 16px; display: grid; min-width: 140px }}
.big {{ font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums }}
h3.sec {{ font-size: 13px; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); margin: 6px 0 -6px }}
.tabla-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px }}
.tabla {{ border-collapse: collapse; width: 100%; min-width: 760px; font-size: 13.5px }}
.tabla th {{ text-align: left; font-size: 12px; color: var(--muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--accent-soft) }}
.tabla td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top }}
.tabla tr:last-child td {{ border-bottom: 0 }}
.tabla.bit {{ min-width: 620px }}
.num {{ font-variant-numeric: tabular-nums; color: var(--muted) }}
.datos {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px 10px; margin: 0 }}
.datos dt {{ color: var(--muted) }}
.datos dd {{ margin: 0; overflow-wrap: anywhere }}
.hall, .ctrl {{ margin: 0; padding-left: 0; list-style: none; display: grid; gap: 8px }}
.ctrl li {{ background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px }}
.muted {{ color: var(--muted) }}
.pie {{ font-size: 12.5px; color: var(--muted); max-width: 80ch }}
.zoom {{ position: fixed; inset: 0; background: rgba(10, 16, 26, .82); display: grid; place-items: center; padding: max(16px, env(safe-area-inset-top, 0px)) max(16px, env(safe-area-inset-right, 0px)) max(16px, env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px)); z-index: 20; cursor: zoom-out }}
.zoom img {{ max-width: min(100%, 1000px); max-height: 100%; background: #ffffff; border-radius: 4px }}
@media (prefers-reduced-motion: no-preference) {{ .exp-tab, .vista-toggle button {{ transition: background .15s, border-color .15s }} }}
</style>
<div class="wrap">
  <header class="top">
    <div class="eyebrow">Maqueta de prevalidación documental · residencia definitiva</div>
    <h1>Prevalida en funcionamiento</h1>
    <p class="lede">Dos expedientes con documentos ficticios cargados en la API de la maqueta el {fecha}, con el motor {e_(res["motor"])}. Todo lo que aparece aquí son respuestas reales del sistema: lo que recibe la persona al cargar cada documento y lo que ve el funcionario al revisar el expediente.</p>
  </header>
  <div class="vias">
    <div class="via-card"><strong>Emisor</strong><span>Los documentos chilenos con código QR se verifican con quien los emitió, sin leerlos con OCR.</span></div>
    <div class="via-card"><strong>Firma electrónica</strong><span>Los documentos firmados se validan por su firma y se leen desde el PDF firmado.</span></div>
    <div class="via-card"><strong>OCR y reglas</strong><span>Los demás se leen desde la imagen; lo dudoso se deriva a revisión humana.</span></div>
  </div>
  <div class="controles">
    <div class="exp-tabs" role="tablist" aria-label="Expedientes">{"".join(tabs)}</div>
    <div class="vista-toggle" role="group" aria-label="Vista">
      <button type="button" data-vista-btn="persona" aria-pressed="true">Persona solicitante</button>
      <button type="button" data-vista-btn="funcionario" aria-pressed="false">Funcionario</button>
    </div>
  </div>
  {"".join(paneles)}
  <p class="pie">Documentos ficticios con datos inventados; no reproducen el diseño oficial de ningún país. El emisor y la infraestructura de firma son simulados. Toca una imagen para ampliarla. Generado con <code>scripts/demo_expediente.py</code>.</p>
</div>
<div class="zoom" id="zoom" hidden><img id="zoom-img" alt=""></div>
<script>
(function () {{
  var vista = "persona";
  function mostrarVista() {{
    document.querySelectorAll("[data-vista]").forEach(function (el) {{ el.hidden = el.getAttribute("data-vista") !== vista; }});
    document.querySelectorAll("[data-vista-btn]").forEach(function (b) {{ b.setAttribute("aria-pressed", String(b.getAttribute("data-vista-btn") === vista)); }});
  }}
  document.querySelectorAll("[data-vista-btn]").forEach(function (b) {{
    b.addEventListener("click", function () {{ vista = b.getAttribute("data-vista-btn"); mostrarVista(); }});
  }});
  document.querySelectorAll(".exp-tab").forEach(function (t) {{
    t.addEventListener("click", function () {{
      var k = t.getAttribute("data-exp");
      document.querySelectorAll(".exp-tab").forEach(function (o) {{ o.setAttribute("aria-selected", String(o === t)); }});
      document.querySelectorAll(".exp").forEach(function (p) {{ p.hidden = p.id !== "exp-" + k; }});
    }});
  }});
  var zoom = document.getElementById("zoom"), zimg = document.getElementById("zoom-img");
  document.querySelectorAll(".thumb").forEach(function (b) {{
    b.addEventListener("click", function () {{ var i = document.getElementById(b.getAttribute("data-img")); zimg.src = i.src; zimg.alt = i.alt; zoom.hidden = false; }});
  }});
  zoom.addEventListener("click", function () {{ zoom.hidden = true; }});
  document.addEventListener("keydown", function (ev) {{ if (ev.key === "Escape") zoom.hidden = true; }});
  mostrarVista();
}})();
</script>
'''
    if not completo:
        return cuerpo
    return ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + cuerpo + "\n</html>\n")


def resumen_markdown(res: dict) -> str:
    out = [f"## Demostración de la maqueta ({res['fecha']})", ""]
    for e in res["expedientes"]:
        out += [f"### {e['nombre']} ({e['nacionalidad']})", "", "| Documento | Vía | Estado | Mensaje a la persona |",
                "|---|---|---|---|"]
        for d in e["documentos"]:
            r = d["respuesta"]
            out.append(f"| {d['titulo']} | {VIA.get(r['via'], r['via'])} | {ESTADO[r['estado']][0]} | "
                       f"{'; '.join(r['mensajes']) or '—'} |")
        ctrl = "; ".join(h["mensaje"] for h in e["controles_expediente"]) or "sin observaciones"
        out += ["", f"Controles del expediente: {ctrl}. Bitácora íntegra: {'sí' if e['bitacora_integra'] else 'no'}.", ""]
    out.append("El reporte completo está en el artefacto `demo-prevalida` de esta ejecución (archivo `reporte.html`).")
    return "\n".join(out) + "\n"


def main():
    print(f"Generando documentos ficticios en {DOCS}", flush=True)
    expedientes = preparar()
    print("Cargando documentos en la API de la maqueta", flush=True)
    res = ejecutar(expedientes)
    (DEMO / "resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (DEMO / "reporte.html").write_text(reporte(res, completo=True), encoding="utf-8")
    if os.environ.get("DEMO_ARTEFACTO"):
        Path(os.environ["DEMO_ARTEFACTO"]).write_text(reporte(res, completo=False), encoding="utf-8")
    md = resumen_markdown(res)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(md)
    print(f"Reporte: {DEMO / 'reporte.html'}")


if __name__ == "__main__":
    main()
