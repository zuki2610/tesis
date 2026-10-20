"""Motor de reglas de prevalidación.

Principio "advertir, nunca rechazar": cada regla produce solo ALERTA (se informa a la
persona y al funcionario) o REVISION_HUMANA. La fecha de referencia es siempre la fecha
de presentación de la solicitud. Si una lectura no es confiable, las reglas que dependen
de ella no se evalúan y el documento se deriva.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .extraccion import Campo, casi_igual_numero, comparar_nombres
from .mrz import ResultadoMRZ
from .verificacion import normalizar_rut


@dataclass
class Hallazgo:
    tipo: str      # "ALERTA" | "REVISION_HUMANA"
    codigo: str
    mensaje: str


@dataclass
class Contexto:
    fecha_presentacion: date
    nombre_declarado: str
    numero_pasaporte_declarado: str = ""
    paises_residencia_5_anios: list[str] = field(default_factory=list)


def cargar_config(ruta: str | Path) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


class MotorReglas:
    def __init__(self, cfg: dict, umbrales_calibrados: dict | None = None):
        self.cfg = cfg
        self.umbrales = umbrales_calibrados or {}

    def umbral(self, campo: str, idioma: str) -> float:
        return self.umbrales.get((campo, idioma), self.cfg["umbrales"]["defecto"])

    # ------------------------------------------------------------ auxiliares
    @staticmethod
    def _nombre(resultado: str, codigo_doc: str) -> list[Hallazgo]:
        if resultado == "DISTINTO":
            return [Hallazgo("ALERTA", "NOMBRE_NO_COINCIDE", f"El nombre del {codigo_doc} no coincide con el declarado")]
        if resultado == "CASI":
            return [Hallazgo("REVISION_HUMANA", "NOMBRE_CASI_COINCIDE",
                             f"El nombre del {codigo_doc} difiere levemente del declarado: verificar")]
        return []

    def _fecha(self, campo: Campo | None, fecha: date | None, idioma: str, ctx: Contexto,
               plazo: int) -> list[Hallazgo]:
        if campo is None or campo.valor is None or campo.confianza < self.umbral("fecha_emision", idioma):
            return [Hallazgo("REVISION_HUMANA", "FECHA_EMISION_DUDOSO", "Fecha de emisión no leída con confianza")]
        if fecha is None:
            return [Hallazgo("REVISION_HUMANA", "FECHA_NO_INTERPRETABLE",
                             f"No se pudo interpretar la fecha '{campo.valor}'")]
        dias = (ctx.fecha_presentacion - fecha).days
        if dias < 0:
            return [Hallazgo("REVISION_HUMANA", "FECHA_FUTURA", "La fecha de emisión es posterior a la presentación")]
        if dias > plazo:
            return [Hallazgo("ALERTA", "DOCUMENTO_ANTIGUO", f"Emitido hace {dias} días (máximo {plazo})")]
        return []

    # ---------------------------------------------------------- pasaporte
    def pasaporte(self, m: ResultadoMRZ | None, conf: float, ctx: Contexto) -> list[Hallazgo]:
        if m is None:
            return [Hallazgo("REVISION_HUMANA", "MRZ_NO_ENCONTRADA", "No se encontró la zona de lectura mecánica")]
        fallidos = [k for k, v in m.controles.items() if not v]
        if fallidos:
            return [Hallazgo("REVISION_HUMANA", "MRZ_ILEGIBLE",
                             "Dígitos de control no coinciden: " + ", ".join(fallidos))]
        h: list[Hallazgo] = []
        if m.vencimiento and m.vencimiento < ctx.fecha_presentacion:
            exc = (self.cfg.get("excepciones_pais") or {}).get(m.pais_emisor, {}).get("pasaporte_vencido")
            if exc == "revision_humana":
                h.append(Hallazgo("REVISION_HUMANA", "VENCIDO_CON_EXCEPCION",
                                  "Pasaporte vencido: aplicar el criterio vigente para el país emisor"))
            else:
                h.append(Hallazgo("ALERTA", "PASAPORTE_VENCIDO", "El pasaporte está vencido"))
        decl = ctx.numero_pasaporte_declarado
        if decl and m.numero != decl:
            if casi_igual_numero(m.numero, decl):
                # Confusiones que el dígito de control no detecta (p. ej., G y 6).
                h.append(Hallazgo("REVISION_HUMANA", "NUMERO_CASI_COINCIDE",
                                  "El número difiere en caracteres que el OCR suele confundir: verificar"))
            else:
                h.append(Hallazgo("ALERTA", "NUMERO_NO_COINCIDE", "El número del pasaporte no coincide con el declarado"))
        h += self._nombre(comparar_nombres(f"{m.apellidos} {m.nombres}", ctx.nombre_declarado,
                                           ultimo_truncado_a=m.nombre_truncado), "pasaporte")
        return h

    # ---------------------------------------- certificado de antecedentes
    def antecedentes(self, campos: dict[str, Campo], autenticacion: dict, pais: str, idioma: str,
                     ctx: Contexto, fecha_emision: date | None) -> list[Hallazgo]:
        nombre, fecha = campos.get("nombre"), campos.get("fecha_emision")
        if (nombre is None or nombre.valor is None) and (fecha is None or fecha.valor is None):
            # No se reconoció la estructura del documento: no se evalúa ninguna otra regla.
            return [Hallazgo("REVISION_HUMANA", "DOCUMENTO_NO_RECONOCIDO",
                             "No se reconocieron los campos del documento")]
        h: list[Hallazgo] = []
        if nombre is None or nombre.valor is None or nombre.confianza < self.umbral("nombre", idioma):
            h.append(Hallazgo("REVISION_HUMANA", "NOMBRE_DUDOSO", "Nombre no leído con confianza"))
        else:
            h += self._nombre(comparar_nombres(nombre.valor, ctx.nombre_declarado), "certificado")
        h += self._fecha(fecha, fecha_emision, idioma, ctx, self.cfg["plazos_dias"]["antecedentes"])
        requerida = self.cfg.get("autenticacion_por_pais", {}).get(pais, "cualquiera")
        if requerida == "apostilla" and not autenticacion["apostilla"]:
            h.append(Hallazgo("ALERTA", "SIN_APOSTILLA", "No se detectó la apostilla"))
        elif requerida == "legalizacion" and not autenticacion["legalizacion"]:
            h.append(Hallazgo("ALERTA", "SIN_LEGALIZACION", "No se detectó la legalización consular"))
        elif requerida == "cualquiera" and not (autenticacion["apostilla"] or autenticacion["legalizacion"]):
            h.append(Hallazgo("ALERTA", "SIN_APOSTILLA_NI_LEGALIZACION", "No se detectó apostilla ni legalización"))
        return h

    def antecedentes_completitud(self, paises_presentados: set[str], ctx: Contexto) -> list[Hallazgo]:
        faltan = [p for p in ctx.paises_residencia_5_anios if p not in paises_presentados]
        return [Hallazgo("ALERTA", "FALTA_ANTECEDENTES_PAIS",
                         f"Falta certificado de antecedentes de: {', '.join(faltan)}")] if faltan else []

    # ------------------------------------------------ documento privado
    def privado(self, firma: dict | None, campos: dict[str, Campo], idioma: str, ctx: Contexto,
                fecha_emision: date | None) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        if firma is None:
            h.append(Hallazgo("ALERTA", "SIN_FEA", "Documento privado sin firma electrónica avanzada"))
        elif not firma["integra"]:
            h.append(Hallazgo("ALERTA", "FIRMA_INVALIDA", "El contenido firmado fue alterado"))
        elif firma["modificado_tras_firma"]:
            h.append(Hallazgo("ALERTA", "MODIFICADO_TRAS_FIRMA", "Se agregó contenido después de la firma"))
        elif not firma["confiable"]:
            h.append(Hallazgo("REVISION_HUMANA", "FIRMANTE_NO_ACREDITADO",
                              "Firma íntegra, pero el certificado no proviene de un prestador acreditado"))
        else:
            rut_doc = normalizar_rut(campos["rut_empleador"].valor if campos.get("rut_empleador") else "")
            if not firma["rut_firmante"] or rut_doc != firma["rut_firmante"]:
                h.append(Hallazgo("ALERTA", "FIRMANTE_NO_COINCIDE",
                                  "La firma no corresponde al empleador indicado en el documento"))
        nombre = campos.get("nombre")
        if nombre is None or nombre.valor is None or nombre.confianza < self.umbral("nombre", idioma):
            h.append(Hallazgo("REVISION_HUMANA", "NOMBRE_DUDOSO", "Nombre no leído con confianza"))
        else:
            h += self._nombre(comparar_nombres(nombre.valor, ctx.nombre_declarado), "documento")
        h += self._fecha(campos.get("fecha_emision"), fecha_emision, idioma, ctx, self.cfg["plazos_dias"]["privado"])
        return h

    # ----------------------------------------- documento público chileno
    def publico_cl(self, verificacion: dict, ctx: Contexto) -> list[Hallazgo]:
        if not verificacion["qr_leido"]:
            return [Hallazgo("REVISION_HUMANA", "QR_ILEGIBLE", "No se pudo leer el código de verificación")]
        if not verificacion["existe"]:
            return [Hallazgo("ALERTA", "CODIGO_INEXISTENTE", "El código no existe en el registro del emisor")]
        h = []
        r = comparar_nombres(verificacion["titular"], ctx.nombre_declarado)
        if r == "DISTINTO":
            h.append(Hallazgo("ALERTA", "CODIGO_DE_OTRA_PERSONA", "El código de verificación corresponde a otra persona"))
        elif r == "CASI":
            h.append(Hallazgo("REVISION_HUMANA", "NOMBRE_CASI_COINCIDE",
                              "El titular registrado difiere levemente del declarado: verificar"))
        dias = (ctx.fecha_presentacion - verificacion["fecha_emision"]).days
        if dias > self.cfg["plazos_dias"]["publico"]:
            h.append(Hallazgo("ALERTA", "DOCUMENTO_ANTIGUO", f"Emitido hace {dias} días (máximo 60)"))
        return h
