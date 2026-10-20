"""Adaptador OCR con interfaz común (RNF-12).

El resto del sistema solo conoce `MotorOCR.leer()`, que devuelve líneas con texto y
confianza (0-1). Cambiar de proveedor no requiere modificar reglas ni orquestación.

- TesseractOCR: se ejecuta localmente (usado en la demostración).
- TextractOCR y AzureOCR: implementados para la prueba con credenciales; no se
  ejecutaron en esta tesis por no disponer de cuentas en esos servicios.
"""
from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

from .preproceso import preprocesar


@dataclass
class Linea:
    texto: str
    confianza: float  # 0..1
    caja: tuple[int, int, int, int] | None = None


@dataclass
class ResultadoOCR:
    motor: str
    lineas: list[Linea] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def texto(self) -> str:
        return "\n".join(l.texto for l in self.lineas)


class MotorOCR(Protocol):
    nombre: str

    def leer(self, imagen: bytes, idioma: str) -> ResultadoOCR: ...


IDIOMAS_TESS = {"es": "spa", "fr": "fra", "en": "eng"}


class TesseractOCR:
    nombre = "tesseract"

    def __init__(self, tessdata: str | None = None, modelo_mrz: str = "mrz"):
        """`modelo_mrz`: modelo de Tesseract para la MRZ. Por defecto, el modelo `mrz`
        de DoubangoTelecom/tesseractMRZ (licencia BSD-3, entrenado con imágenes de MRZ en
        OCR-B); si no está disponible, se usa `eng`."""
        import pytesseract
        self._pt = pytesseract
        self._cfg = f'--tessdata-dir "{tessdata}" --psm 6' if tessdata else "--psm 6"
        disponibles = set(pytesseract.get_languages(config=self._cfg))
        self.modelo_mrz = modelo_mrz if modelo_mrz in disponibles else "eng"

    def leer(self, imagen: bytes, idioma: str) -> ResultadoOCR:
        t0 = time.perf_counter()
        img = preprocesar(Image.open(io.BytesIO(imagen)))
        lang = IDIOMAS_TESS.get(idioma, "eng") + "+eng"
        d = self._pt.image_to_data(img, lang=lang, config=self._cfg, output_type=self._pt.Output.DICT)
        grupos: dict[tuple, list[int]] = {}
        for i, txt in enumerate(d["text"]):
            if txt.strip() and float(d["conf"][i]) >= 0:
                grupos.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        lineas = []
        for idx in grupos.values():
            palabras = [d["text"][i] for i in idx]
            confs = [float(d["conf"][i]) / 100 for i in idx]
            x0 = min(d["left"][i] for i in idx); y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx); y1 = max(d["top"][i] + d["height"][i] for i in idx)
            lineas.append(Linea(" ".join(palabras), min(confs), (x0, y0, x1, y1)))
        lineas.sort(key=lambda l: (l.caja[1], l.caja[0]))
        return ResultadoOCR(self.nombre, lineas, time.perf_counter() - t0)


    def leer_mrz(self, imagen: bytes) -> ResultadoOCR:
        """Lectura especializada de la franja inferior con alfabeto restringido a la MRZ.

        Se hacen dos pasadas (escala original y ampliada x2); el extractor elige la
        primera MRZ cuyos dígitos de control sean válidos."""
        t0 = time.perf_counter()
        img = preprocesar(Image.open(io.BytesIO(imagen)))
        w, h = img.size
        base = img.crop((0, int(h * 0.70), w, h))
        cfg = self._cfg + " -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
        lineas: list[Linea] = []
        for escala in (1, 2):
            franja = base if escala == 1 else base.resize((base.width * 2, base.height * 2), Image.LANCZOS)
            d = self._pt.image_to_data(franja, lang=self.modelo_mrz, config=cfg, output_type=self._pt.Output.DICT)
            grupos: dict[tuple, list[int]] = {}
            for i, txt in enumerate(d["text"]):
                if txt.strip() and float(d["conf"][i]) >= 0:
                    grupos.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
            pas = []
            for idx in grupos.values():
                txt = "".join(d["text"][i] for i in idx)
                conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
                pas.append(Linea(txt, conf, (min(d["left"][i] for i in idx), min(d["top"][i] for i in idx), 0, 0)))
            pas.sort(key=lambda l: (l.caja[1], l.caja[0]))
            lineas += pas + [Linea("", 0.0)]
        return ResultadoOCR(self.nombre + "-mrz", lineas, time.perf_counter() - t0)


class TextractOCR:
    """Amazon Textract. Documentos: AnalyzeDocument con FORMS; MRZ: DetectDocumentText.

    La región es obligatoria y se toma de AWS_REGION: debe elegirse según la política de
    localización de datos (RNF-09). Antes de usarlo, activar la política de exclusión de
    servicios de IA en AWS Organizations."""
    nombre = "textract"

    def __init__(self, region: str | None = None):
        import boto3
        region = region or os.environ.get("AWS_REGION")
        if not region:
            raise ValueError("Defina AWS_REGION según la política de localización de datos")
        self._c = boto3.client("textract", region_name=region)

    @staticmethod
    def _lineas(r) -> list[Linea]:
        return [Linea(b["Text"], b["Confidence"] / 100) for b in r["Blocks"] if b["BlockType"] == "LINE"]

    def leer(self, imagen: bytes, idioma: str) -> ResultadoOCR:
        t0 = time.perf_counter()
        r = self._c.analyze_document(Document={"Bytes": imagen}, FeatureTypes=["FORMS"])
        return ResultadoOCR(self.nombre, self._lineas(r), time.perf_counter() - t0)

    def leer_mrz(self, imagen: bytes) -> ResultadoOCR:
        t0 = time.perf_counter()
        r = self._c.detect_document_text(Document={"Bytes": imagen})
        return ResultadoOCR(self.nombre + "-mrz", self._lineas(r), time.perf_counter() - t0)


class AzureOCR:
    """Azure AI Document Intelligence (modelo prebuilt-read)."""
    nombre = "azure"

    def __init__(self, endpoint: str | None = None, clave: str | None = None):
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
        self._c = DocumentIntelligenceClient(endpoint or os.environ["AZURE_DI_ENDPOINT"],
                                             AzureKeyCredential(clave or os.environ["AZURE_DI_KEY"]))

    def leer(self, imagen: bytes, idioma: str) -> ResultadoOCR:
        t0 = time.perf_counter()
        poller = self._c.begin_analyze_document("prebuilt-read", body=imagen, content_type="application/octet-stream")
        res = poller.result()
        lineas = []
        for p in res.pages or []:
            confs = {w.span.offset: w.confidence for w in (p.words or [])}
            for l in p.lines or []:
                cs = [c for off, c in confs.items() if any(s.offset <= off < s.offset + s.length for s in l.spans)]
                lineas.append(Linea(l.content, min(cs) if cs else 0.0))
        return ResultadoOCR(self.nombre, lineas, time.perf_counter() - t0)


def crear_motor(nombre: str, **kw) -> MotorOCR:
    return {"tesseract": TesseractOCR, "textract": TextractOCR, "azure": AzureOCR}[nombre](**kw)
