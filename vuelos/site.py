"""Genera la página de Yasui Flights (docs/index.html) para GitHub Pages.

Es un solo archivo HTML con los datos adentro (ofertas, precios de hoy y la lista de
lugares para el buscador) + vendor/supabase.js para el login con código.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List

from .util import DOCS, env, guardar_json, supabase_url

AQUI = Path(__file__).parent
PLANTILLA = AQUI / "app.html"
SUPABASE_JS = AQUI / "static" / "supabase.js"


def config_publica(config: dict) -> dict:
    """Lo que la página necesita saber. Todo esto es público (la publishable key está hecha para eso)."""
    return {
        "sitio": config.get("sitio", {}).get("nombre", "Yasui Flights"),
        "supabase_url": supabase_url(),
        "supabase_key": env("SUPABASE_PUBLISHABLE_KEY"),
        "remitente": env("GMAIL_USER") or config.get("email", {}).get("nombre_remitente", "Yasui Flights"),
    }


def armar_datos(config: dict, generado: str, hoy: str, ofertas: List[dict], precios: Dict[str, dict],
                lugares: list, fuentes: List[dict], demo: bool = False) -> dict:
    populares = [f["ciudad"] for f in config.get("favoritos", [])]
    return {
        "config": config_publica(config),
        "origen": config.get("origen", "SJU"),
        "generado": generado,
        "hoy": hoy,
        "demo": demo,
        "fuentes": fuentes,
        "ofertas": ofertas,
        "precios": precios,
        "populares": populares,
        "lugares": lugares,
    }


def generar(datos: dict, archivo: str = "index.html", carpeta: Path = DOCS) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    js = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = PLANTILLA.read_text(encoding="utf-8").replace("/*__DATOS__*/null", js)
    salida = carpeta / archivo
    salida.write_text(html, encoding="utf-8")
    (carpeta / "vendor").mkdir(exist_ok=True)
    destino_js = carpeta / "vendor" / "supabase.js"
    if not destino_js.exists() or destino_js.stat().st_size != SUPABASE_JS.stat().st_size:
        shutil.copyfile(SUPABASE_JS, destino_js)
    (carpeta / ".nojekyll").write_text("", encoding="utf-8")
    if archivo == "index.html":
        sin_lugares = {k: v for k, v in datos.items() if k != "lugares"}
        guardar_json(carpeta / "ofertas.json", sin_lugares)
    return salida
