"""Utilidades compartidas: configuración, .env, HTTP, archivos JSON, fechas y distancias."""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
CACHE = DATA / "cache"
DOCS = RAIZ / "docs"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def log(msg: str) -> None:
    print(msg, flush=True)


def aviso(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- config / env

def cargar_config(ruta: Optional[Path] = None) -> dict:
    ruta = ruta or (RAIZ / "config.yaml")
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cargar_env(ruta: Optional[Path] = None) -> None:
    """Lee un archivo .env sencillo (CLAVE=valor). Lo que ya esté en el entorno gana."""
    ruta = ruta or (RAIZ / ".env")
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        if clave and valor and not os.environ.get(clave):
            os.environ[clave] = valor


def env(nombre: str, defecto: str = "") -> str:
    return os.environ.get(nombre, defecto).strip()


# ---------------------------------------------------------------- HTTP

def sesion_http() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,es;q=0.8"})
    return s


# ---------------------------------------------------------------- JSON

def leer_json(ruta: Path, defecto: Any) -> Any:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def guardar_json(ruta: Path, datos: Any, compacto: bool = False) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        if compacto:
            json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=False)
    tmp.replace(ruta)


# ---------------------------------------------------------------- fechas

def ahora() -> datetime:
    return datetime.now(timezone.utc)


def ahora_iso() -> str:
    return ahora().replace(microsecond=0).isoformat()


def hoy_pr() -> str:
    """Fecha de hoy en Puerto Rico (UTC-4, sin horario de verano)."""
    return (ahora() - timedelta(hours=4)).date().isoformat()


def desde_iso(texto: Optional[str]) -> Optional[datetime]:
    if not texto:
        return None
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def horas_desde(texto: Optional[str]) -> float:
    dt = desde_iso(texto)
    if dt is None:
        return 1e9
    return (ahora() - dt).total_seconds() / 3600


# ---------------------------------------------------------------- distancia

def millas(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta (gran círculo) en millas."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
