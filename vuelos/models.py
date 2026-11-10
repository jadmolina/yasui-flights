"""Estructura de una tarifa encontrada por cualquier fuente."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Tarifa:
    fuente: str                      # "travelpayouts" | "google" | "feed"
    origen: str                      # SJU
    destino: str                     # código IATA (ciudad o aeropuerto)
    precio: float                    # USD
    ida_y_vuelta: bool = True
    salida: Optional[str] = None     # YYYY-MM-DD
    regreso: Optional[str] = None    # YYYY-MM-DD
    aerolinea: Optional[str] = None
    aerolinea_iata: Optional[str] = None  # código (B6, WN, AA...) para el logo
    escalas: Optional[int] = None
    link: Optional[str] = None
    encontrado: Optional[str] = None # ISO
    sitio: Optional[str] = None      # nombre del feed / sitio
    titulo: Optional[str] = None     # título original del post (feeds)
    es_error: bool = False           # el sitio lo marcó como error de tarifa
    destino_texto: Optional[str] = None  # texto del destino tal como lo publicó un feed
    origen_texto: Optional[str] = None   # texto del origen (feeds que salen de EE.UU.)
    puente: bool = False                 # True = sale de una ciudad puente (no de SJU)
    alterno: bool = False                # True = sale de otro aeropuerto de PR (Aguadilla)

    # se llenan después (lugares.enriquecer)
    destino_nombre: Optional[str] = None
    pais: Optional[str] = None
    pais_nombre: Optional[str] = None
    region: Optional[str] = None
    distancia: Optional[float] = None    # millas (solo ida)
    favorito: bool = False
    aeropuerto: Optional[str] = None     # aeropuerto para Google Flights

    extra: dict = field(default_factory=dict)

    def clave_ruta(self) -> str:
        base = f"{self.destino}:{'rt' if self.ida_y_vuelta else 'ow'}"
        return f"{self.origen}>{base}" if (self.puente or self.alterno) else base

    def clave_unica(self) -> str:
        if self.fuente == "feed" and self.link:
            base = self.link
        else:
            base = f"{self.origen}|{self.destino}|{self.ida_y_vuelta}|{self.salida}|{self.regreso}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)
