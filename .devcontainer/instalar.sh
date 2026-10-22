#!/usr/bin/env bash
# Instalación del entorno de la maqueta en GitHub Codespaces (Ubuntu 24.04, Tesseract 5.3.4).
set -euo pipefail
cd "$(dirname "$0")/../maqueta"
sudo apt-get update
sudo apt-get install -y --no-install-recommends tesseract-ocr fonts-dejavu-core fonts-ocr-b
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
bash scripts/descargar_modelos.sh
python -m pytest -q tests
python scripts/demo_expediente.py
echo
echo "Listo. El servidor se inicia solo al abrir el Codespace; si no, ejecuta:"
echo "  cd maqueta && python scripts/servidor_demo.py"
