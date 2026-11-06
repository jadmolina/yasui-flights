"""Feeds (RSS) de sitios que publican mistake fares y ofertas.

Se queda solo con los posts que SALEN de San Juan / Puerto Rico.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import feedparser

from ..models import Tarifa
from ..util import aviso, log, sesion_http, horas_desde

PR = r"(?:san juan|puerto rico|\bSJU\b)"
ERROR = re.compile(r"error fare|mistake fare|fare glitch|price glitch|glitch fare|\berror\b|\bmistake\b", re.I)
PRECIO = re.compile(r"(?:US\$|USD\s?|\$)\s?([\d][\d,]*(?:\.\d\d)?)|([\d][\d,]*)\s?(?:USD|dollars)", re.I)
PREFIJOS = re.compile(
    r"^(?:\[[^\]]*\]\s*|error fare[:\s\-–—]*|mistake fare[:\s\-–—]*|hot[:\s\-–—]*|non-?stop(?: flights)? from\s+|"
    r"(?:cheap )?flights? from\s+|from\s+)+",
    re.I,
)


def _limpiar(texto: str) -> str:
    texto = html.unescape(texto or "")
    texto = texto.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _precio(texto: str) -> Optional[float]:
    for m in PRECIO.finditer(texto):
        valor = m.group(1) or m.group(2)
        try:
            n = float(valor.replace(",", ""))
        except ValueError:
            continue
        if 20 <= n <= 5000:
            return n
    return None


def _tipo_viaje(texto: str) -> bool:
    """True = ida y vuelta (lo normal en estos sitios)."""
    if re.search(r"one[- ]?way", texto, re.I) and not re.search(r"round[- ]?trip", texto, re.I):
        return False
    return True


def analizar_titulo(titulo: str) -> Optional[Tuple[str, str, bool]]:
    """Devuelve (origen, destino, sale_de_pr) o None si no entiende el título.

    Formatos que reconoce:
      Secret Flying:   "San Juan, Puerto Rico to Madrid, Spain for only $299 USD roundtrip"
      The Flight Deal: "jetBlue: San Juan - Paris, France. $338. Roundtrip, including all Taxes"
    """
    t = _limpiar(titulo)
    sin_prefijo = PREFIJOS.sub("", t)
    candidatos = []
    # The Flight Deal: "Aerolínea: Origen - Destino. $123 ..."
    m = re.match(r"^[^:]{2,40}:\s*(.+?)\s+-\s+(.+?)(?:\s*\(and vice versa\))?\.\s*(?:\$|US\$)", t)
    if m:
        candidatos.append((m.group(1), m.group(2)))
    # Secret Flying / genérico: "Origen to Destino for only $..."
    m = re.match(r"^(.+?)\s+to\s+(.+?)(?:\s+(?:for only|for|from|starting at|under|-)\s+(?:US\$|\$|USD|\d)|\s+(?:US\$|\$)|[.!]|$)", sin_prefijo, re.I)
    if m:
        candidatos.append((m.group(1), m.group(2)))
    # Genérico: "SJU-NRT $450" o "San Juan - Tokyo $450"
    m = re.search(rf"({PR}[^-–>]*)\s*(?:-|–|>|→)\s*([A-Za-z][^$]+?)\s+(?:for\s+)?\$", sin_prefijo, re.I)
    if m:
        candidatos.append((m.group(1), m.group(2)))
    for origen, destino in candidatos:
        origen, destino = origen.strip(), destino.strip(" .,-")
        if not origen or not destino or re.search(PR, destino, re.I):
            continue  # vuelos HACIA Puerto Rico no nos sirven
        return origen, destino, bool(re.search(PR, origen, re.I))
    return None


class Feeds:
    nombre = "Feeds de ofertas"

    def __init__(self, config: dict):
        self.config = config
        self.conf = config.get("feeds", {})
        self.http = sesion_http()
        self.estado: dict = {}

    def _leer(self, url: str):
        r = self.http.get(url, timeout=25, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
        r.raise_for_status()
        return feedparser.parse(r.content)

    def buscar(self) -> List[Tarifa]:
        dias = float(self.conf.get("dias_a_mostrar", 10))
        tarifas: List[Tarifa] = []
        vistos = set()
        for feed in self.conf.get("lista", []):
            nombre, url = feed["nombre"], feed["url"]
            try:
                parsed = self._leer(url)
            except Exception as e:  # noqa: BLE001
                self.estado[nombre] = {"ok": False, "error": str(e)[:160]}
                aviso(f"No pude leer {nombre}: {str(e)[:120]}")
                continue
            encontrados = 0
            for item in parsed.entries:
                titulo = _limpiar(item.get("title", ""))
                link = item.get("link")
                if not titulo or not link or link in vistos:
                    continue
                fecha = None
                for campo in ("published_parsed", "updated_parsed"):
                    if item.get(campo):
                        fecha = datetime(*item[campo][:6], tzinfo=timezone.utc).isoformat()
                        break
                if fecha and horas_desde(fecha) > dias * 24:
                    continue
                ruta = analizar_titulo(titulo)
                if not ruta:
                    continue
                if not ruta[2] and re.search(r"\b(?:many|various|multiple|several)\b.*\bcities\b|\bcities\b", ruta[0], re.I):
                    continue  # "US cities to Tokyo": no sabemos de qué ciudad sale
                resumen = _limpiar(re.sub(r"<[^>]+>", " ", item.get("summary", "")))[:400]
                precio = _precio(titulo) or _precio(resumen)
                if not precio:
                    continue
                vistos.add(link)
                desde_pr = ruta[2]
                encontrados += 1 if desde_pr else 0
                tarifas.append(Tarifa(
                    fuente="feed", sitio=nombre, origen=self.config.get("origen", "SJU") if desde_pr else "",
                    destino="", destino_texto=ruta[1], origen_texto=None if desde_pr else ruta[0], precio=precio,
                    ida_y_vuelta=_tipo_viaje(titulo + " " + resumen), link=link, encontrado=fecha,
                    titulo=titulo, es_error=bool(ERROR.search(titulo)), puente=not desde_pr,
                ))
            if not parsed.entries:
                self.estado[nombre] = {"ok": False, "error": "el sitio no devolvió posts (puede estar bloqueando)"}
                continue
            self.estado[nombre] = {"ok": True, "posts": len(parsed.entries), "desde_pr": encontrados}
        n_pr = sum(1 for t in tarifas if not t.puente)
        log(f"  Feeds: {n_pr} ofertas saliendo de Puerto Rico y {len(tarifas) - n_pr} desde otras ciudades (para combinados)")
        return tarifas
