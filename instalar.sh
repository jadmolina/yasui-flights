#!/bin/bash
# Prepara todo en tu Mac: crea un entorno de Python e instala lo necesario.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo ""
  echo "Ojo: tu Python es más viejo que 3.10, y Google Flights necesita 3.10+."
  echo "Para tenerlo:  brew install python@3.12   (o el instalador de python.org)"
  echo "Sigo con el Python que tienes; todo funciona menos Google Flights."
  echo ""
  PY=python3
fi

echo "Usando $($PY --version)"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creé el archivo .env: ábrelo y pon tus claves."
fi

echo ""
echo "Listo. Para buscar vuelos:   bash buscar.sh"
echo "Para ver la página de ejemplo: bash buscar.sh --demo"
