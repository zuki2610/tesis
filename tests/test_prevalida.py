import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prevalida.bitacora import Bitacora  # noqa: E402
from prevalida.extraccion import parsear_fecha, similitud_nombres  # noqa: E402
from prevalida.mrz import digito_control, generar_td3, parsear, parsear_con_reparacion  # noqa: E402
from prevalida.reglas import Contexto, MotorReglas, cargar_config  # noqa: E402

CFG = cargar_config(Path(__file__).resolve().parent.parent / "config" / "reglas.yaml")


def test_especimen_oaci():
    # Espécimen publicado en el Doc 9303 de la OACI
    r = parsear("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10")
    assert r.valida and len(r.controles) == 5
    assert r.apellidos == "ERIKSSON" and r.nombres == "ANNA MARIA"


def test_digito_control():
    assert digito_control("L898902C3") == 6
    assert digito_control("740812") == 2


def test_generar_y_validar():
    l1, l2 = generar_td3("VEN", "Pérez Muñoz", "María José", "AB1234567", "VEN", date(1990, 1, 2), "F", date(2030, 3, 4))
    assert parsear(l1, l2).valida


def test_reparacion_caracter_insertado():
    l1, l2 = generar_td3("HTI", "Joseph", "Kervens", "X04132302", "HTI", date(1961, 4, 26), "M", date(2034, 10, 6))
    roto = l2[:12] + "1" + l2[12:]  # el OCR lee la "I" de HTI como "1I"
    r, reparada = parsear_con_reparacion(l1, roto)
    assert reparada and r.valida and r.nacionalidad == "HTI"


def test_g6_no_detectable():
    # Limitación del estándar: G (16) y 6 (6) difieren en 10, el dígito de control no cambia.
    assert digito_control("3G8795489") == digito_control("368795489")


def test_nombres_orden_y_tildes():
    assert similitud_nombres("PEREZ GONZALEZ MARIA JOSE", "María José Pérez González") == 1.0
    assert similitud_nombres("Rosa Pérez González", "María José Pérez González") < 0.9


def test_fechas():
    assert parsear_fecha("12/O3/2026") == date(2026, 3, 12)
    assert parsear_fecha("14 octobre 2026") == date(2026, 10, 14)


def test_reglas_no_rechazan_y_excepcion_venezuela():
    m = MotorReglas(CFG)
    l1, l2 = generar_td3("VEN", "Rojas", "Ana", "AB1234567", "VEN", date(1990, 1, 2), "F", date(2025, 1, 1))
    h = m.pasaporte(parsear(l1, l2), 0.9, Contexto(date(2026, 10, 1), "Ana Rojas", "AB1234567"))
    assert [x.codigo for x in h] == ["VENCIDO_CON_EXCEPCION"]
    assert all(x.tipo in ("ALERTA", "REVISION_HUMANA") for x in h)


def test_antecedentes_varios_paises():
    m = MotorReglas(CFG)
    ctx = Contexto(date(2026, 10, 1), "Ana Rojas", paises_residencia_5_anios=["VEN", "PER"])
    assert m.antecedentes_completitud({"VEN"}, ctx)[0].codigo == "FALTA_ANTECEDENTES_PAIS"


def test_bitacora_detecta_alteracion():
    b = Bitacora()
    for i in range(3):
        b.registrar("s1", "sistema", "evento", {"i": i})
    assert b.verificar()
    b.db.execute("UPDATE eventos SET datos='{\"i\": 99}' WHERE id=2")
    assert not b.verificar()
