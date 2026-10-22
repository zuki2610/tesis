#!/usr/bin/env bash
# Descarga los modelos de Tesseract que usa la maqueta en ./tessdata.
# - spa, fra, eng y osd: modelos rápidos oficiales (tessdata_fast).
# - mrz: modelo para la tipografía OCR-B de la MRZ (DoubangoTelecom, licencia BSD-3).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tessdata
for m in spa fra eng osd; do
  if [ ! -s "tessdata/$m.traineddata" ]; then
    curl -fsSL -o "tessdata/$m.traineddata" "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$m.traineddata"
  fi
done
if [ ! -s tessdata/mrz.traineddata ]; then
  curl -fsSL -o tessdata/mrz.traineddata \
    https://raw.githubusercontent.com/DoubangoTelecom/tesseractMRZ/master/tessdata_best/mrz.traineddata
fi
echo "e44f5b7a6bdd3f382ef3bfa84ee0057f5897946a84a094c26910e0a124f3a9bd  tessdata/mrz.traineddata" | sha256sum -c -
ls -l tessdata
