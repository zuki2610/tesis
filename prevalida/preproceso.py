"""Preprocesamiento de imagen previo al OCR: corrección de inclinación y de iluminación."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def angulo_inclinacion(gris: np.ndarray) -> float:
    """Estima la inclinación del texto (grados) probando rotaciones y maximizando la
    varianza del perfil de proyección horizontal."""
    _, bw = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    peq = cv2.resize(bw, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    h, w = peq.shape
    mejor, mejor_a = -1.0, 0.0
    for a in np.arange(-6, 6.01, 0.25):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(peq, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        v = float(np.var(r.sum(axis=1)))
        if v > mejor:
            mejor, mejor_a = v, a
    return mejor_a


def preprocesar(img: Image.Image) -> Image.Image:
    gris = np.array(img.convert("L"))
    a = angulo_inclinacion(gris)
    if abs(a) > 0.2:
        h, w = gris.shape
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        gris = cv2.warpAffine(gris, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
    # Corrección de iluminación: divide por el fondo estimado con un desenfoque amplio.
    fondo = cv2.GaussianBlur(gris, (0, 0), 25)
    norm = cv2.divide(gris, fondo, scale=255)
    return Image.fromarray(norm)
