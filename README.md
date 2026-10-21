# Prevalida — prototipo de prevalidación documental para la residencia definitiva

Prototipo de la tesis *Prevalidación documental mediante interoperabilidad, firma electrónica y
reconocimiento óptico de caracteres para la residencia definitiva en el Servicio Nacional de
Migraciones de Chile* (Magíster en Ingeniería Informática, UBO).

Implementa los tres principios de diseño de la tesis:

1. **Primero el emisor**: los documentos públicos chilenos se verifican por su código QR contra el
   emisor; los documentos con firma electrónica avanzada se validan por su firma (Ley 19.799) y,
   si la firma es válida, su texto se toma del PDF firmado; solo el resto pasa por OCR.
2. **Advertir, nunca rechazar; ante la duda, derivar**: las reglas solo generan `ALERTA` o
   `REVISION_HUMANA`, y no se evalúan sobre lecturas no confiables.
3. **Equidad calibrada**: las métricas se reportan por idioma y país.

> Todos los documentos de los corpus son **ficticios** y generados por programa.
> No se usa ningún dato personal real.

## Estructura

```
prevalida/
  mrz.py           MRZ TD3 (OACI Doc 9303): 5 dígitos de control, correcciones por posición,
                   reparación de un carácter insertado, nombres truncados
  preproceso.py    Corrección de inclinación e iluminación
  ocr.py           Adaptador OCR con interfaz común: Tesseract (local), Textract (análisis de
                   formularios) y Azure Document Intelligence (requieren credenciales)
  extraccion.py    Campos por etiqueta (límite de palabra, valor en la línea siguiente), fechas,
                   comparación de nombres (Levenshtein por palabra: EXACTO/SUBCONJUNTO/CASI/DISTINTO),
                   apostilla y legalización
  reglas.py        Motor de reglas (config/reglas.yaml): pasaporte, antecedentes, privado, QR, completitud
  verificacion.py  QR contra el emisor; firma electrónica con pyHanko (integridad, cambios posteriores
                   a la firma, cadena de confianza, RUT del firmante); texto del PDF con pypdf
  bitacora.py      Cadena de hashes SHA-256 con ancla externa autenticada (HMAC): detecta
                   modificación, eliminación de los últimos eventos y reescritura
  pipeline.py      Orquestación por vía (emisor, firma, OCR) y controles de expediente
  api.py           API REST (FastAPI)
config/reglas.yaml Plazos, umbral, idiomas, autenticación por país, excepciones por país
scripts/
  generar_corpus.py              Corpus de desarrollo (generador v2)
  generar_corpus_adversarial.py  Corpus adversarial (escrito después de congelar el código)
  evaluar.py                     Evaluación: campos, detección, omisiones, alertas, MRZ, QR, firma,
                                 latencia, bitácora
  comparar_modelo_mrz.py         Modelo `eng` frente al modelo para OCR-B en la MRZ
  figuras.py                     Resumen, figuras y tabla por condición de la tesis
tests/             40 pruebas automatizadas (incluye el espécimen de MRZ del Doc 9303)
```

## Requisitos

- Python 3.11 o superior y Tesseract 5 (se usó 5.3.4: `apt install tesseract-ocr`).
- `pip install -r requirements.txt`
- Modelos de Tesseract en `./tessdata`:

```bash
mkdir -p tessdata && cd tessdata
for m in spa fra eng osd; do
  curl -LO https://github.com/tesseract-ocr/tessdata_fast/raw/main/$m.traineddata
done
# Modelo para la tipografía OCR-B de la MRZ (DoubangoTelecom, licencia BSD-3)
curl -L -o mrz.traineddata \
  https://raw.githubusercontent.com/DoubangoTelecom/tesseractMRZ/master/tessdata_best/mrz.traineddata
sha256sum mrz.traineddata   # e44f5b7a6bdd3f382ef3bfa84ee0057f5897946a84a094c26910e0a124f3a9bd
cd ..
```

Si falta `mrz.traineddata`, el adaptador usa `eng` para la MRZ, con resultados mucho peores
(ver `resultados_modelo_mrz.json`).

## Versiones evaluadas (etiquetas git)

| Etiqueta | Contenido |
|---|---|
| `iteracion-3` | Estado previo a la revisión de código (generador v1). Las iteraciones 1 y 2 no se versionaron por separado. |
| `congelado-evaluacion` | Iteración 4: código congelado antes de escribir el corpus adversarial. |
| `iteracion-5` | Correcciones de lógica tras la evaluación adversarial. |

## Corpus y resultados

| Corpus | Generador | Semilla | Resultados |
|---|---|---|---|
| `corpus_D` (desarrollo, 350 doc.) | `generar_corpus.py` | 20261022 | `resultados_D_it4` (iteración 4), `resultados_D5` (iteración 5) |
| `corpus_ADV` (adversarial, 246 doc.) | `generar_corpus_adversarial.py` | 20261023 | `resultados_ADV_it4` (código congelado) |
| `corpus_ADV2` (adversarial, 246 doc.) | `generar_corpus_adversarial.py` | 20261024 | `resultados_ADV2` (iteración 5) |

Los corpus no se incluyen en el repositorio por su tamaño; se regeneran así:

```bash
CORPUS_DIR=corpus_D    SEED=20261022 python scripts/generar_corpus.py
CORPUS_DIR=corpus_ADV  SEED=20261023 python scripts/generar_corpus_adversarial.py
CORPUS_DIR=corpus_ADV2 SEED=20261024 python scripts/generar_corpus_adversarial.py
```

Las imágenes, el registro del emisor simulado y la verdad de referencia se regeneran idénticos
(verificado para `corpus_ADV2`). Las claves de la infraestructura de firma de prueba se generan en
cada ejecución, por lo que los PDF firmados cambian byte a byte, sin alterar su clasificación esperada.

### Reproducir las evaluaciones

```bash
# Iteración 5 (código actual)
CORPUS_DIR=corpus_D    OUT_DIR=resultados_D5   python scripts/evaluar.py
CORPUS_DIR=corpus_ADV2 OUT_DIR=resultados_ADV2 PRUEBA_TODO=1 python scripts/evaluar.py

# Iteración 4 (código congelado) con el mismo script de evaluación
git worktree add ../prevalida_it4 congelado-evaluacion
cp scripts/evaluar.py ../prevalida_it4/scripts/ && ln -s "$PWD/tessdata" ../prevalida_it4/tessdata
(cd ../prevalida_it4 && CORPUS_DIR=$OLDPWD/corpus_D   OUT_DIR=$OLDPWD/resultados_D_it4 python scripts/evaluar.py)
(cd ../prevalida_it4 && CORPUS_DIR=$OLDPWD/corpus_ADV OUT_DIR=$OLDPWD/resultados_ADV_it4 PRUEBA_TODO=1 python scripts/evaluar.py)
git worktree remove ../prevalida_it4

# Comparación de modelos de la MRZ, figuras y tablas de la tesis, pruebas
CORPUS_DIR=corpus_D python scripts/comparar_modelo_mrz.py
python scripts/figuras.py
python -m pytest tests
```

`PRUEBA_TODO=1` evalúa el corpus completo; se usa en los corpus adversariales porque nada se
ajustó con ellos. En esos corpus, los umbrales "calibrados" que informa `evaluar.py` no son
válidos (la mitad de calibración está dentro del conjunto evaluado): la tesis reporta solo los
resultados con el umbral por defecto (0,80).

`resultados_iteracion1` a `resultados_iteracion3`, `resultados_mrz_por_pais.*` y
`resultados_resumen_iteraciones.json` son registros históricos del generador v1 y no se
reproducen con el código actual.

## Defectos conocidos del código evaluado

- La apostilla no se detecta si el OCR altera el espaciado de su leyenda (p. ej., "deLa Haya");
  el sistema alerta que falta.
- Si el nombre de la MRZ está truncado y el nombre declarado omite un segundo nombre, la
  comparación no aplica el prefijo truncado y puede alertar o derivar.
- Un nombre con dos palabras unidas por un error de tipeo ("JeanmBaptiste") se compara como el
  nombre de otra persona.
- Firma electrónica: solo se valida la primera firma del PDF (una segunda firma se interpreta como
  contenido agregado tras firmar); se exige que el RUT del certificado sea el del empleador, lo que
  falla si firma un representante; no se verifican revocación ni sello de tiempo.

No se corrigieron para no alterar el código evaluado; cualquier corrección debe reevaluarse con
un corpus nuevo.

## Ejecutar la API

```bash
EMISOR_JSON=corpus_D/emisor_simulado.json RAICES_FEA=corpus_D/certs/raiz_acreditada.pem \
  uvicorn prevalida.api:app --reload
# POST /solicitudes                   (nombre, numero_pasaporte, paises_residencia)
# POST /solicitudes/{id}/documentos   (tipo, idioma, pais, imagen, pdf opcional)
# GET  /solicitudes/{id}              expediente para el funcionario
# POST /bitacora/ancla                emite un ancla de la bitácora
```

## Motores en la nube

`PREVALIDA_MOTOR=textract` (región en `AWS_REGION`) o `PREVALIDA_MOTOR=azure`
(`AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`). Estos adaptadores están implementados pero **no se
ejecutaron** en la tesis por no disponer de cuentas en esos servicios. En AWS, activar antes la
política de exclusión de servicios de IA de AWS Organizations.
