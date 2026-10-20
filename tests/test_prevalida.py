import io
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prevalida.bitacora import Bitacora  # noqa: E402
from prevalida.extraccion import (Campo, casi_igual_numero, comparar_nombres, desde_texto,  # noqa: E402
                                  detectar_autenticacion, parsear_fecha)
from prevalida.mrz import digito_control, generar_td3, parsear, parsear_con_reparacion  # noqa: E402
from prevalida.reglas import Contexto, MotorReglas, cargar_config  # noqa: E402
from prevalida.verificacion import validar_fea  # noqa: E402

CFG = cargar_config(Path(__file__).resolve().parent.parent / "config" / "reglas.yaml")
HOY = date(2026, 10, 1)


# ------------------------------------------------------------------ MRZ
def test_especimen_oaci():
    r = parsear("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10")
    assert r.valida and len(r.controles) == 5
    assert r.apellidos == "ERIKSSON" and r.nombres == "ANNA MARIA"


def test_digito_control():
    assert digito_control("L898902C3") == 6
    assert digito_control("740812") == 2


def test_reparacion_caracter_insertado():
    l1, l2 = generar_td3("HTI", "Joseph", "Kervens", "X04132302", "HTI", date(1961, 4, 26), "M", date(2034, 10, 6))
    r, reparada = parsear_con_reparacion(l1, l2[:12] + "1" + l2[12:])
    assert reparada and r.valida and r.nacionalidad == "HTI"


def test_g6_no_detectable_por_digito_y_regla_deriva():
    assert digito_control("3G8795489") == digito_control("368795489")
    assert casi_igual_numero("368795489", "3G8795489")
    l1, l2 = generar_td3("COL", "Rojas", "Ana", "368795489", "COL", date(1990, 1, 2), "F", date(2030, 1, 1))
    h = MotorReglas(CFG).pasaporte(parsear(l1, l2), 0.9, Contexto(HOY, "Ana Rojas", "3G8795489"))
    assert [x.codigo for x in h] == ["NUMERO_CASI_COINCIDE"]


def test_pasaporte_vencido_sin_excepcion_vigente():
    l1, l2 = generar_td3("VEN", "Rojas", "Ana", "AB1234567", "VEN", date(1990, 1, 2), "F", date(2025, 1, 1))
    h = MotorReglas(CFG).pasaporte(parsear(l1, l2), 0.9, Contexto(HOY, "Ana Rojas", "AB1234567"))
    assert [x.codigo for x in h] == ["PASAPORTE_VENCIDO"]


def test_excepcion_configurable():
    cfg = dict(CFG, excepciones_pais={"VEN": {"pasaporte_vencido": "revision_humana"}})
    l1, l2 = generar_td3("VEN", "Rojas", "Ana", "AB1234567", "VEN", date(1990, 1, 2), "F", date(2025, 1, 1))
    h = MotorReglas(cfg).pasaporte(parsear(l1, l2), 0.9, Contexto(HOY, "Ana Rojas", "AB1234567"))
    assert [x.codigo for x in h] == ["VENCIDO_CON_EXCEPCION"]


# --------------------------------------------------------------- nombres
@pytest.mark.parametrize("a,b,esperado", [
    ("PEREZ GONZALEZ MARIA JOSE", "María José Pérez González", "EXACTO"),
    ("Carmen Rosa Muñoz Núñez", "Carmen Muñoz Núñez", "SUBCONJUNTO"),       # segundo nombre omitido
    ("Valdés Hernández", "Valdés Fernández", "CASI"),                        # un carácter: revisión humana
    ("JQSE PEREZ", "José Pérez", "CASI"),                                     # error de OCR: revisión humana
    ("Ana Rodríguez Martínez", "Ana Rodríguez Hernández", "DISTINTO"),
    ("Ana Lucía Pérez", "Ana María Pérez", "DISTINTO"),
    ("Jean-Baptiste Pierre", "JEAN BAPTISTE PIERRE", "EXACTO"),
])
def test_comparar_nombres(a, b, esperado):
    assert comparar_nombres(a, b) == esperado


def test_nombre_truncado_mrz():
    assert comparar_nombres("SAINT FLEUR JEAN BAPTISTE MARIE GUERL", "Marie Guerline Jean-Baptiste Saint-Fleur",
                            ultimo_truncado_a=True) == "EXACTO"


# ----------------------------------------------------------------- fechas
@pytest.mark.parametrize("s,esperado", [
    ("12/O3/2026", date(2026, 3, 12)), ("14 octobre 2026", date(2026, 10, 14)), ("1er mars 2026", date(2026, 3, 1)),
    ("01 de marzo del 2026", date(2026, 3, 1)), ("2026-03-01", date(2026, 3, 1)), ("01.03.2026", date(2026, 3, 1)),
    ("1° de marzo de 2026", date(2026, 3, 1)), ("marzo de 2026", None),
])
def test_fechas(s, esperado):
    assert parsear_fecha(s) == esperado


def test_fecha_no_interpretable_deriva():
    campos = {"nombre": Campo("nombre", "Ana Rojas", 0.95), "fecha_emision": Campo("fecha_emision", "el mes pasado", 0.95)}
    h = MotorReglas(CFG).antecedentes(campos, {"apostilla": True, "legalizacion": False}, "PER", "es",
                                      Contexto(HOY, "Ana Rojas"), None)
    assert [x.codigo for x in h] == ["FECHA_NO_INTERPRETABLE"]


# ------------------------------------------------- apostilla y legalización
def test_autenticacion_por_pais():
    m = MotorReglas(CFG)
    campos = {"nombre": Campo("nombre", "Ana Rojas", 0.95), "fecha_emision": Campo("fecha_emision", "20/09/2026", 0.95)}
    leg = detectar_autenticacion(desde_texto("LÉGALISATION\nConsulado de Chile en Puerto Príncipe"))
    assert leg == {"apostilla": False, "legalizacion": True}
    # Haití no es parte de la Convención de la Apostilla: con legalización no hay alerta.
    assert m.antecedentes(campos, leg, "HTI", "fr", Contexto(HOY, "Ana Rojas"), date(2026, 9, 20)) == []
    assert [x.codigo for x in m.antecedentes(campos, leg, "PER", "es", Contexto(HOY, "Ana Rojas"),
                                             date(2026, 9, 20))] == ["SIN_APOSTILLA"]
    solo_palabra = detectar_autenticacion(desde_texto("APOSTILLA"))
    assert solo_palabra["apostilla"] is False  # requiere también la mención a la Convención


def test_documento_no_reconocido_no_dispara_otras_reglas():
    campos = {"nombre": Campo("nombre", None, 0.0), "fecha_emision": Campo("fecha_emision", None, 0.0)}
    h = MotorReglas(CFG).antecedentes(campos, {"apostilla": False, "legalizacion": False}, "PER", "es",
                                      Contexto(HOY, "Ana Rojas"), None)
    assert [x.codigo for x in h] == ["DOCUMENTO_NO_RECONOCIDO"]


def test_completitud_por_pais():
    ctx = Contexto(HOY, "Ana Rojas", paises_residencia_5_anios=["VEN", "PER"])
    assert MotorReglas(CFG).antecedentes_completitud({"VEN"}, ctx)[0].codigo == "FALTA_ANTECEDENTES_PAIS"


# ------------------------------------------------------- firma electrónica
@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    d = tmp_path_factory.mktemp("pki")
    ahora = datetime.now(timezone.utc)
    kr = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nr = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Raiz de prueba")])
    raiz = (x509.CertificateBuilder().subject_name(nr).issuer_name(nr).public_key(kr.public_key())
            .serial_number(1).not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
            .sign(kr, hashes.SHA256()))
    kh = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nh = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Empleador"),
                    x509.NameAttribute(NameOID.SERIAL_NUMBER, "76.123.456-7")])
    hoja = (x509.CertificateBuilder().subject_name(nh).issuer_name(nr).public_key(kh.public_key())
            .serial_number(2).not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=30))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .sign(kr, hashes.SHA256()))
    (d / "raiz.pem").write_bytes(raiz.public_bytes(serialization.Encoding.PEM))
    (d / "hoja.pem").write_bytes(hoja.public_bytes(serialization.Encoding.PEM))
    (d / "clave.pem").write_bytes(kh.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); c = canvas.Canvas(buf); c.drawString(60, 780, "RUT empleador: 76.123.456-7"); c.save()
    s = signers.SimpleSigner.load(str(d / "clave.pem"), str(d / "hoja.pem"), ca_chain_files=(str(d / "raiz.pem"),))
    pdf = signers.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(buf.getvalue())),
                           signers.PdfSignatureMetadata(field_name="F"), signer=s).getvalue()
    return pdf, (d / "raiz.pem").read_bytes()


def test_firma_valida_y_rut(pki):
    pdf, raiz = pki
    f = validar_fea(pdf, [raiz])
    assert f["integra"] and f["confiable"] and not f["modificado_tras_firma"] and f["rut_firmante"] == "761234567"


def test_actualizacion_incremental_detectada(pki):
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    pdf, raiz = pki
    w = IncrementalPdfFileWriter(io.BytesIO(pdf))
    page = w.root["/Pages"]["/Kids"][0].get_object()
    ref = w.add_object(generic.StreamObject(stream_data=b"BT /F1 20 Tf 300 200 Td (Liquido: 9.999.999) Tj ET"))
    contenidos = page["/Contents"]
    page["/Contents"] = generic.ArrayObject(
        (list(contenidos) if isinstance(contenidos, generic.ArrayObject) else [contenidos]) + [ref])
    w.update_container(page)
    out = io.BytesIO(); w.write(out)
    f = validar_fea(out.getvalue(), [raiz])
    assert f["modificado_tras_firma"]
    campos = {"nombre": Campo("nombre", "Ana Rojas", 1.0), "fecha_emision": Campo("fecha_emision", "20/09/2026", 1.0),
              "rut_empleador": Campo("rut_empleador", "76.123.456-7", 1.0)}
    h = MotorReglas(CFG).privado(f, campos, "es", Contexto(HOY, "Ana Rojas"), date(2026, 9, 20))
    assert [x.codigo for x in h] == ["MODIFICADO_TRAS_FIRMA"]


def test_firmante_distinto_del_empleador(pki):
    pdf, raiz = pki
    f = validar_fea(pdf, [raiz])
    campos = {"nombre": Campo("nombre", "Ana Rojas", 1.0), "fecha_emision": Campo("fecha_emision", "20/09/2026", 1.0),
              "rut_empleador": Campo("rut_empleador", "99.888.777-6", 1.0)}
    h = MotorReglas(CFG).privado(f, campos, "es", Contexto(HOY, "Ana Rojas"), date(2026, 9, 20))
    assert [x.codigo for x in h] == ["FIRMANTE_NO_COINCIDE"]


# ---------------------------------------------------------------- bitácora
def test_bitacora_detecta_modificacion_truncamiento_y_reescritura():
    b = Bitacora()
    for i in range(3):
        b.registrar("s1", "sistema", "evento", {"i": i})
    ancla = b.ancla()
    assert b.verificar(ancla)
    b.db.execute("UPDATE eventos SET datos='{\"i\": 99}' WHERE id=2")
    assert not b.verificar()
    b2 = Bitacora()
    for i in range(3):
        b2.registrar("s1", "sistema", "evento", {"i": i})
    a2 = b2.ancla()
    b2.db.execute("DELETE FROM eventos WHERE id=3")
    assert b2.verificar() and not b2.verificar(a2)        # truncamiento: solo lo detecta el ancla
    b3 = Bitacora()
    for i in range(3):
        b3.registrar("s1", "sistema", "evento", {"i": i})
    a3 = b3.ancla()
    b3.db.execute("DELETE FROM eventos")
    for i in range(3):
        b3.registrar("s1", "sistema", "evento", {"i": i + 10})  # cadena reescrita y recalculada
    assert b3.verificar() and not b3.verificar(a3)


# ------------------------------------------------- iteración 5 (etiquetas)
from prevalida.extraccion import extraer_etiquetados  # noqa: E402


@pytest.mark.parametrize("texto,nombre", [
    ("Nombre del padre: Luis Rojas\nNombre: Ana Pérez", "Ana Pérez"),   # trampa
    ("NOMBRE\nANA PÉREZ\nFECHA DE EMISIÓN\n3/9/2026", "ANA PÉREZ"),     # etiqueta y valor en líneas separadas
    ("NOMBRE COMPLETO: Ana Pérez", "Ana Pérez"),
    ("Nom et prénoms : Wisly Dorvil", "Wisly Dorvil"),
])
def test_etiquetas(texto, nombre):
    assert extraer_etiquetados(desde_texto(texto), "antecedentes")["nombre"].valor == nombre


def test_nom_no_confunde_nombre():
    c = extraer_etiquetados(desde_texto("NOMBREE: x\nNombres y apellidos"), "antecedentes")["nombre"]
    assert c.valor is None


def test_etiqueta_sin_valor_es_none():
    c = extraer_etiquetados(desde_texto("Trabajador:\nFecha de emisión:"), "liquidacion")
    assert c["nombre"].valor is None


@pytest.mark.parametrize("s,esperado", [("3 de agosto, 2026", date(2026, 8, 3)),
                                         ("Septiembre 16 de 2026", date(2026, 9, 16)),
                                         ("16/09/26", None)])
def test_fechas_iteracion5(s, esperado):
    assert parsear_fecha(s) == esperado


def test_rut_no_leido_deriva(pki):
    pdf, raiz = pki
    f = validar_fea(pdf, [raiz])
    campos = {"nombre": Campo("nombre", "Ana Rojas", 1.0), "fecha_emision": Campo("fecha_emision", "20/09/2026", 1.0),
              "rut_empleador": Campo("rut_empleador", None, 0.0)}
    h = MotorReglas(CFG).privado(f, campos, "es", Contexto(HOY, "Ana Rojas"), date(2026, 9, 20))
    assert [x.codigo for x in h] == ["RUT_NO_LEIDO"]
