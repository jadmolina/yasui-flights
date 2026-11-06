#!/bin/bash
# Corre el buscador y abre la página.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Primero corre:  bash instalar.sh"
  exit 1
fi
.venv/bin/python run.py "$@" || exit $?
if [[ " $* " == *" --demo "* ]] || [[ " $* " == *" --probar-email "* ]]; then
  open docs/demo.html 2>/dev/null
else
  open docs/index.html 2>/dev/null
fi
exit 0
