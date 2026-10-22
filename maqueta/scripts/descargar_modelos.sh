#!/usr/bin/env bash
# Descarga los modelos de Tesseract que usa la maqueta en ./tessdata.
# - spa, fra, eng y osd: modelos rápidos oficiales (tessdata_fast).
# - mrz: modelo para la tipografía OCR-B de la MRZ (DoubangoTelecom, licencia BSD-3).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tessdata
for m in spa fra eng osd; do
  if [ ! -s "tessdata/$m.traineddata" ]; then
    curl -fsSL -o "tessdata/$m.traineddata" "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/$m.traineddata"
  fi
done
if [ ! -s tessdata/mrz.traineddata ]; then
  curl -fsSL -o tessdata/mrz.traineddata \
    https://raw.githubusercontent.com/DoubangoTelecom/tesseractMRZ/master/tessdata_best/mrz.traineddata
fi
# Mismos modelos que se usaron en la tesis (verificados por su hash SHA-256).
sha256sum -c - <<'HASHES'
6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464  tessdata/spa.traineddata
ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca  tessdata/fra.traineddata
7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2  tessdata/eng.traineddata
9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff  tessdata/osd.traineddata
e44f5b7a6bdd3f382ef3bfa84ee0057f5897946a84a094c26910e0a124f3a9bd  tessdata/mrz.traineddata
HASHES
ls -l tessdata
