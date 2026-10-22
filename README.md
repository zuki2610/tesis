# Prevalidación documental para la residencia definitiva

Tesis de Magíster en Ingeniería Informática (Universidad Bernardo O'Higgins) de Trina Isabel
Palacios Hernández: *Prevalidación documental mediante interoperabilidad, firma electrónica y
reconocimiento óptico de caracteres para la residencia definitiva en el Servicio Nacional de
Migraciones de Chile: arquitectura y maqueta funcional*.

| Carpeta o archivo | Contenido |
|---|---|
| `paper_ocr_sermig.pdf` | El paper de tesis |
| `paper_ocr_sermig.tex`, `fig_*`, `tabla_*.tex` | Fuente en LaTeX (compilar con XeLaTeX) |
| `maqueta/` | Código de la maqueta Prevalida, generadores de documentos ficticios, pruebas y resultados ([README](maqueta/README.md)) |

## Ver la maqueta funcionando

**Con GitHub Actions, sin instalar nada.** Pestaña *Actions* → *Demostración de la maqueta* →
*Run workflow*. En unos minutos corre las 40 pruebas automatizadas y carga dos expedientes
ficticios en la API de la maqueta. La tabla con las respuestas aparece en el resumen de la
ejecución; el reporte completo (`reporte.html`, con lo que ve la persona solicitante y lo que ve
el funcionario) se descarga desde el artefacto `demo-prevalida`. También corre solo con cada
`push` a `main`.

**Con GitHub Codespaces, en el navegador.** Botón *Code* → *Codespaces* → *Create codespace on
main*. La primera vez instala Tesseract, los modelos y las dependencias y genera la
demostración (unos minutos); luego abre el puerto 8000 con:

- `/demo/reporte.html`: los dos expedientes de la demostración.
- `/docs`: la API, para crear una solicitud y cargar documentos ficticios de `maqueta/demo/documentos/`.

Si el servidor no se inicia solo: `cd maqueta && python scripts/servidor_demo.py`.

Todos los documentos son ficticios, con datos inventados; el emisor y la infraestructura de
firma son simulados.

## Versiones de la maqueta

Las etiquetas `iteracion-3`, `congelado-evaluacion` (iteración 4, código congelado antes de la
prueba adversarial) e `iteracion-5` marcan las versiones evaluadas que documenta el Anexo A del
paper. En esas etiquetas el código de la maqueta está en la raíz, porque se incorporó a este
repositorio con su historial.
