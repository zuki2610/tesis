# Prevalida — prototipo de prevalidación de documentos migratorios

Prototipo de la tesis *Automatización de la prevalidación de documentos migratorios en el Servicio
Nacional de Migraciones de Chile* (Magíster en Ingeniería Informática, UBO).

Implementa los tres principios de diseño de la tesis:

1. **Primero el emisor**: los documentos públicos chilenos se verifican por su código QR contra el
   emisor; los documentos con firma electrónica avanzada se validan por su firma (Ley 19.799);
   solo el resto pasa por OCR.
2. **Advertir, nunca rechazar**: las reglas solo generan `ALERTA` o `REVISION_HUMANA`.
3. **Equidad calibrada**: el umbral de confianza se calibra por idioma y las métricas se reportan
   por idioma y país.

> Todos los documentos del corpus son **ficticios** y generados por `scripts/generar_corpus.py`.
> No se usa ningún dato personal real.

## Estructura

```
prevalida/
  mrz.py           Validación MRZ TD3 (5 dígitos de control, OACI Doc 9303) y reparación por dígitos de control
  preproceso.py    Corrección de inclinación e iluminación
  ocr.py           Adaptador OCR con interfaz común: Tesseract (local), Textract y Azure (requieren credenciales)
  extraccion.py    Extracción de campos, fechas, normalización y similitud de nombres (Jaro-Winkler por tokens)
  reglas.py        Motor de reglas configurable (config/reglas.yaml), con excepciones por país
  verificacion.py  Verificación de QR contra el emisor y validación de firma electrónica avanzada (pyHanko)
  bitacora.py      Bitácora con encadenamiento de hashes SHA-256 (detecta alteraciones)
  pipeline.py      Orquestación: emisor -> firma -> OCR + reglas
  api.py           API REST (FastAPI)
config/reglas.yaml Plazos, umbrales, excepciones por país
scripts/
  generar_corpus.py  Corpus sintético con verdad de referencia (pasaportes VEN/PER/COL/BOL/HTI, certificados ES/FR,
                     liquidaciones firmadas, certificados con QR, documentos en idioma no soportado)
  evaluar.py         Evaluación: calibración/prueba, Clopper-Pearson, falsas alertas, MRZ, firma, QR, latencia
tests/             Pruebas unitarias (incluye el espécimen oficial de la OACI)
```

## Requisitos

- Python 3.11 o superior y Tesseract 5 (`apt install tesseract-ocr`)
- Modelos `spa` y `fra` de `tessdata_fast` en `./tessdata` (junto con `eng` y `osd`)
- `pip install -r requirements.txt`

## Reproducir los resultados de la tesis

```bash
# Iteración 1, 2 y 3 (cada una con un corpus nuevo e independiente)
CORPUS_DIR=corpus_A SEED=20261019 python scripts/generar_corpus.py
CORPUS_DIR=corpus_B SEED=20261020 python scripts/generar_corpus.py
CORPUS_DIR=corpus_C SEED=20261021 python scripts/generar_corpus.py
CORPUS_DIR=corpus_C OUT_DIR=resultados_iteracion3 python scripts/evaluar.py
python -m pytest tests
```

Nota: las iteraciones 1 y 2 se ejecutaron con versiones anteriores del código (ver la sección de
iteraciones de la tesis); al reejecutarlas con el código actual se obtienen los resultados de la iteración 3.

## Ejecutar la API

```bash
EMISOR_JSON=corpus_C/emisor_simulado.json RAICES_FEA=corpus_C/certs/raiz_acreditada.pem \
  uvicorn prevalida.api:app --reload
# POST /solicitudes                      (nombre, numero_pasaporte, paises_residencia)
# POST /solicitudes/{id}/documentos      (tipo, idioma, imagen, pdf opcional)
# GET  /solicitudes/{id}                 expediente para el funcionario
```

## Motores en la nube

`PREVALIDA_MOTOR=textract` (región con `AWS_REGION`) o `PREVALIDA_MOTOR=azure`
(`AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`). Estos adaptadores están implementados pero **no se ejecutaron**
en la tesis por no disponer de cuentas en esos servicios. En AWS, activar antes la política de
exclusión de servicios de IA de AWS Organizations.
