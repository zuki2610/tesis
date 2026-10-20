"""Motor de reglas de prevalidación.

Principio de diseño "advertir, nunca rechazar": cada regla produce solo
ALERTA (se informa a la persona y al funcionario) o REVISION_HUMANA.
La fecha de referencia es siempre la fecha de presentación de la solicitud.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .extraccion import Campo, similitud_nombres
from .mrz import ResultadoMRZ


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

    # ---------------------------------------------------------- pasaporte
    def pasaporte(self, m: ResultadoMRZ | None, conf: float, ctx: Contexto) -> list[Hallazgo]:
        if m is None:
            return [Hallazgo("REVISION_HUMANA", "MRZ_NO_ENCONTRADA", "No se encontró la zona de lectura mecánica")]
        fallidos = [k for k, v in m.controles.items() if not v]
        if fallidos:
            # Si la MRZ no es confiable, no se evalúan sus fechas ni su número.
            return [Hallazgo("REVISION_HUMANA", "MRZ_ILEGIBLE",
                             "Dígitos de control no coinciden: " + ", ".join(fallidos))]
        h: list[Hallazgo] = []
        if m.vencimiento and m.vencimiento < ctx.fecha_presentacion:
            exc = self.cfg.get("excepciones_pais", {}).get(m.pais_emisor, {}).get("pasaporte_vencido")
            if exc == "revision_humana":
                h.append(Hallazgo("REVISION_HUMANA", "VENCIDO_CON_EXCEPCION",
                                  "Pasaporte vencido: aplicar criterio vigente para el país emisor"))
            else:
                h.append(Hallazgo("ALERTA", "PASAPORTE_VENCIDO", "El pasaporte está vencido"))
        if ctx.numero_pasaporte_declarado and m.numero != ctx.numero_pasaporte_declarado:
            h.append(Hallazgo("ALERTA", "NUMERO_NO_COINCIDE", "El número del pasaporte no coincide con el declarado"))
        nombre_mrz = f"{m.apellidos} {m.nombres}"
        if similitud_nombres(nombre_mrz, ctx.nombre_declarado) < self.cfg["umbrales"]["nombre_similitud"]:
            h.append(Hallazgo("ALERTA", "NOMBRE_NO_COINCIDE", "El nombre del pasaporte no coincide con el declarado"))
        return h

    # ---------------------------------------- certificado de antecedentes
    def antecedentes(self, campos: dict[str, Campo], apostilla: bool, idioma: str, ctx: Contexto,
                     fecha_emision: date | None) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        for nombre in ("nombre", "fecha_emision"):
            c = campos.get(nombre)
            if c is None or c.valor is None or c.confianza < self.umbral(nombre, idioma):
                h.append(Hallazgo("REVISION_HUMANA", f"{nombre.upper()}_DUDOSO",
                                  f"Campo '{nombre}' no leído con confianza suficiente"))
        if any(x.tipo == "REVISION_HUMANA" and x.codigo == "FECHA_EMISION_DUDOSO" for x in h) or fecha_emision is None:
            pass
        else:
            dias = (ctx.fecha_presentacion - fecha_emision).days
            if dias > self.cfg["plazos_dias"]["antecedentes"]:
                h.append(Hallazgo("ALERTA", "ANTECEDENTES_ANTIGUO", f"Emitido hace {dias} días (máximo 60)"))
        if not any(x.codigo == "NOMBRE_DUDOSO" for x in h):
            if similitud_nombres(campos["nombre"].valor, ctx.nombre_declarado) < self.cfg["umbrales"]["nombre_similitud"]:
                h.append(Hallazgo("ALERTA", "NOMBRE_NO_COINCIDE", "El nombre del certificado no coincide con el declarado"))
        if not apostilla:
            h.append(Hallazgo("ALERTA", "SIN_APOSTILLA", "No se detectó apostilla o legalización"))
        return h

    def antecedentes_completitud(self, paises_presentados: set[str], ctx: Contexto) -> list[Hallazgo]:
        faltan = [p for p in ctx.paises_residencia_5_anios if p not in paises_presentados]
        return [Hallazgo("ALERTA", "FALTA_ANTECEDENTES_PAIS",
                         f"Falta certificado de antecedentes de: {', '.join(faltan)}")] if faltan else []

    # ------------------------------------------------ documento privado
    def privado(self, firma: dict | None, campos: dict[str, Campo], idioma: str, ctx: Contexto,
                fecha_emision: date | None) -> list[Hallazgo]:
        h: list[Hallazgo] = []
        if firma is not None:
            if not firma["integra"]:
                h.append(Hallazgo("ALERTA", "FIRMA_INVALIDA", "El documento fue modificado después de firmado"))
            elif not firma["confiable"]:
                h.append(Hallazgo("REVISION_HUMANA", "FIRMANTE_NO_ACREDITADO",
                                  "Firma íntegra, pero el certificado no proviene de un prestador acreditado"))
        else:
            h.append(Hallazgo("ALERTA", "SIN_FEA", "Documento privado sin firma electrónica avanzada ni verificación"))
        c = campos.get("fecha_emision")
        if c is None or c.valor is None or c.confianza < self.umbral("fecha_emision", idioma) or fecha_emision is None:
            h.append(Hallazgo("REVISION_HUMANA", "FECHA_EMISION_DUDOSO", "Fecha de emisión no leída con confianza"))
        else:
            dias = (ctx.fecha_presentacion - fecha_emision).days
            if dias > self.cfg["plazos_dias"]["privado"]:
                h.append(Hallazgo("ALERTA", "DOCUMENTO_ANTIGUO", f"Emitido hace {dias} días (máximo 30)"))
        n = campos.get("nombre")
        if n is None or n.valor is None or n.confianza < self.umbral("nombre", idioma):
            h.append(Hallazgo("REVISION_HUMANA", "NOMBRE_DUDOSO", "Nombre no leído con confianza"))
        elif similitud_nombres(n.valor, ctx.nombre_declarado) < self.cfg["umbrales"]["nombre_similitud"]:
            h.append(Hallazgo("ALERTA", "NOMBRE_NO_COINCIDE", "El nombre no coincide con el declarado"))
        return h

    # ----------------------------------------- documento público chileno
    def publico_cl(self, verificacion: dict, ctx: Contexto) -> list[Hallazgo]:
        if not verificacion["qr_leido"]:
            return [Hallazgo("REVISION_HUMANA", "QR_ILEGIBLE", "No se pudo leer el código de verificación")]
        if not verificacion["existe"]:
            return [Hallazgo("ALERTA", "CODIGO_INEXISTENTE", "El código no existe en el registro del emisor")]
        h = []
        if similitud_nombres(verificacion["titular"], ctx.nombre_declarado) < self.cfg["umbrales"]["nombre_similitud"]:
            h.append(Hallazgo("ALERTA", "CODIGO_DE_OTRA_PERSONA",
                              "El código de verificación corresponde a otra persona"))
        dias = (ctx.fecha_presentacion - verificacion["fecha_emision"]).days
        if dias > self.cfg["plazos_dias"]["publico"]:
            h.append(Hallazgo("ALERTA", "DOCUMENTO_ANTIGUO", f"Emitido hace {dias} días (máximo 60)"))
        return h
