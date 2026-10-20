"""Orquestación de la prevalidación de un documento.

Clasifica el documento por tipo y lo envía por la vía de mayor confiabilidad:
emisor (QR/código) -> firma electrónica avanzada -> OCR con reglas.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from . import extraccion as ex
from .bitacora import Bitacora
from .ocr import MotorOCR
from .reglas import Contexto, Hallazgo, MotorReglas
from .verificacion import RegistroEmisor, validar_fea, verificar_qr


@dataclass
class ResultadoDocumento:
    tipo: str
    via: str
    campos: dict = field(default_factory=dict)
    hallazgos: list[Hallazgo] = field(default_factory=list)
    segundos: float = 0.0
    motor: str = ""

    @property
    def estado(self) -> str:
        if any(h.tipo == "REVISION_HUMANA" for h in self.hallazgos):
            return "REVISION_HUMANA"
        if self.hallazgos:
            return "CON_ALERTAS"
        return "PREVALIDADO"


class Prevalidador:
    def __init__(self, motor: MotorOCR, reglas: MotorReglas, emisor: RegistroEmisor,
                 raices_fea: list[bytes], bitacora: Bitacora | None = None):
        self.motor, self.reglas, self.emisor, self.raices = motor, reglas, emisor, raices_fea
        self.bitacora = bitacora or Bitacora()

    def procesar(self, solicitud: str, tipo: str, idioma: str, imagen: bytes | None,
                 ctx: Contexto, pdf: bytes | None = None) -> ResultadoDocumento:
        t0 = time.perf_counter()
        if idioma not in self.reglas.cfg["idiomas_soportados"] and tipo != "certificado_publico_cl":
            r = ResultadoDocumento(tipo, "directo_humano",
                                   hallazgos=[Hallazgo("REVISION_HUMANA", "IDIOMA_NO_SOPORTADO",
                                                       "Idioma no soportado por el motor OCR")])
        elif tipo == "certificado_publico_cl":
            v = verificar_qr(imagen, self.emisor)
            r = ResultadoDocumento(tipo, "emisor", campos={k: str(v.get(k)) for k in v},
                                   hallazgos=self.reglas.publico_cl(v, ctx))
        elif tipo == "pasaporte":
            # Si el motor ofrece lectura especializada de la MRZ, se usa; si no, la lectura general.
            o = self.motor.leer_mrz(imagen) if hasattr(self.motor, "leer_mrz") else self.motor.leer(imagen, idioma)
            m, conf = ex.extraer_mrz(o)
            campos = {} if m is None else {"numero": m.numero, "apellidos": m.apellidos, "nombres": m.nombres,
                                           "vencimiento": str(m.vencimiento), "controles": m.controles,
                                           "confianza": conf}
            r = ResultadoDocumento(tipo, "ocr_mrz", campos, self.reglas.pasaporte(m, conf, ctx), motor=o.motor)
        elif tipo == "antecedentes_extranjero":
            o = self.motor.leer(imagen, idioma)
            campos = ex.extraer_etiquetados(o, "antecedentes")
            fecha = ex.parsear_fecha(campos["fecha_emision"].valor)
            apost, _ = ex.detectar_apostilla(o)
            r = ResultadoDocumento(tipo, "ocr", {k: asdict(c) for k, c in campos.items()} | {"apostilla": apost},
                                   self.reglas.antecedentes(campos, apost, idioma, ctx, fecha), motor=o.motor)
        elif tipo == "liquidacion":
            firma = validar_fea(pdf, self.raices) if pdf else None
            o = self.motor.leer(imagen, idioma)
            campos = ex.extraer_etiquetados(o, "liquidacion")
            fecha = ex.parsear_fecha(campos["fecha_emision"].valor)
            r = ResultadoDocumento(tipo, "firma_y_ocr" if firma else "ocr",
                                   {k: asdict(c) for k, c in campos.items()} | {"firma": firma},
                                   self.reglas.privado(firma, campos, idioma, ctx, fecha), motor=o.motor)
        else:
            raise ValueError(f"Tipo de documento desconocido: {tipo}")
        r.segundos = time.perf_counter() - t0
        self.bitacora.registrar(solicitud, "sistema", "prevalidacion",
                                {"tipo": tipo, "via": r.via, "estado": r.estado,
                                 "hallazgos": [h.codigo for h in r.hallazgos]})
        return r
