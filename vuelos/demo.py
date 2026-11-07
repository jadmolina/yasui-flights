"""Datos de ejemplo para ver la página y el email sin tokens ni internet."""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List

from .lugares import Lugares, _normal
from .models import Tarifa
from .sources.google_flights import link_google
from .util import ahora_iso, hoy_pr

# code: (nombre, país, lat, lon)
CIUDADES = {
    "TYO": ("Tokyo", "JP", 35.69, 139.69), "OSA": ("Osaka", "JP", 34.69, 135.50),
    "HNL": ("Honolulu", "US", 21.31, -157.86), "OGG": ("Kahului", "US", 20.89, -156.43),
    "NYC": ("New York", "US", 40.71, -74.01), "ORL": ("Orlando", "US", 28.54, -81.38),
    "MIA": ("Miami", "US", 25.76, -80.19), "BOS": ("Boston", "US", 42.36, -71.06),
    "CHI": ("Chicago", "US", 41.88, -87.63), "LAX": ("Los Angeles", "US", 34.05, -118.24),
    "LAS": ("Las Vegas", "US", 36.17, -115.14), "YTO": ("Toronto", "CA", 43.65, -79.38),
    "YMQ": ("Montreal", "CA", 45.50, -73.57), "YVR": ("Vancouver", "CA", 49.28, -123.12),
    "MAD": ("Madrid", "ES", 40.42, -3.70), "BCN": ("Barcelona", "ES", 41.39, 2.17),
    "LON": ("London", "GB", 51.51, -0.13), "PAR": ("Paris", "FR", 48.86, 2.35),
    "ROM": ("Rome", "IT", 41.90, 12.50), "LIS": ("Lisbon", "PT", 38.72, -9.14),
    "SEL": ("Seoul", "KR", 37.57, 126.98), "BOG": ("Bogotá", "CO", 4.71, -74.07),
    "SFO": ("San Francisco", "US", 37.77, -122.42), "SAP": ("Sapporo", "JP", 43.06, 141.35),
}
NOMBRES_ES = {"SEL": "Seúl", "BOG": "Bogotá", "LAX": "Los Ángeles", "NYC": "Nueva York"}

NORMAL = {
    "TYO": 1100, "OSA": 1150, "HNL": 750, "OGG": 820, "NYC": 220, "ORL": 160, "MIA": 170, "BOS": 260,
    "CHI": 300, "LAX": 420, "LAS": 400, "YTO": 480, "YMQ": 450, "YVR": 650, "MAD": 650, "BCN": 700,
    "LON": 720, "PAR": 780, "ROM": 800, "LIS": 600, "SEL": 1100, "BOG": 380, "SFO": 430, "SAP": 1250,
}


def lugares_demo(config: dict) -> Lugares:
    l = Lugares(config)
    for code, (name, pais, lat, lon) in CIUDADES.items():
        l.ciudades[code] = {"name": name, "es": NOMBRES_ES.get(code), "country": pais, "lat": lat, "lon": lon}
        l.por_nombre[_normal(name)] = code
    l.paises = {"JP": "Japan", "US": "United States", "CA": "Canada", "ES": "Spain", "GB": "United Kingdom",
                "FR": "France", "IT": "Italy", "PT": "Portugal", "KR": "South Korea", "CO": "Colombia"}
    l.paises_por_nombre = {_normal(v): k for k, v in l.paises.items()}
    l.aerolineas = {"NH": "ANA", "B6": "JetBlue", "NK": "Spirit", "IB": "Iberia", "AA": "American",
                    "TP": "TAP Air Portugal", "AF": "Air France", "KE": "Korean Air", "UA": "United", "AC": "Air Canada"}
    for f in config.get("favoritos", []):
        l.por_nombre[_normal(f["nombre"])] = f["ciudad"]
    return l


def historial_demo() -> dict:
    rnd = random.Random(7)
    hist = {}
    for code, base in NORMAL.items():
        serie = {}
        for i in range(30, 0, -1):
            d = (date.fromisoformat(hoy_pr()) - timedelta(days=i)).isoformat()
            serie[d] = round(base * rnd.uniform(0.85, 1.2))
        hist[f"{code}:rt"] = serie
    return hist


def _d(dias: int) -> str:
    return (date.today() + timedelta(days=dias)).isoformat()


def tarifas_demo() -> List[Tarifa]:
    ya = ahora_iso()
    hace_6h = (date.today()).isoformat() + "T06:00:00+00:00"

    def tp(dest, precio, sal, dur, al, esc, rt=True):
        return Tarifa(fuente="travelpayouts", sitio="Aviasales", origen="SJU", destino=dest, precio=precio,
                      ida_y_vuelta=rt, salida=_d(sal), regreso=_d(sal + dur) if rt else None, aerolinea=al,
                      escalas=esc, link="https://www.aviasales.com/search/SJU" + dest, encontrado=ya)

    def gf(dest_ap, precio, sal, dur, al, esc):
        return Tarifa(fuente="google", sitio="Google Flights", origen="SJU", destino=dest_ap, precio=precio,
                      salida=_d(sal), regreso=_d(sal + dur), aerolinea=al, escalas=esc,
                      link=link_google("SJU", dest_ap, _d(sal), _d(sal + dur)), encontrado=ya)

    def feed(sitio, titulo, precio, error=False, destino_texto=""):
        return Tarifa(fuente="feed", sitio=sitio, origen="SJU", destino="", destino_texto=destino_texto, precio=precio,
                      link="https://www.secretflying.com/posts/ejemplo-" + destino_texto.split(",")[0].lower(),
                      encontrado=hace_6h, titulo=titulo, es_error=error)

    def puente(origen, dest, precio, sal, dur, al, esc):
        return Tarifa(fuente="travelpayouts", sitio="Aviasales", origen=origen, destino=dest, precio=precio,
                      salida=_d(sal), regreso=_d(sal + dur), aerolinea=al, escalas=esc, puente=True,
                      link=f"https://www.aviasales.com/search/{origen}{dest}", encontrado=ya,
                      extra={"aeropuerto_origen": {"LAX": "LAX", "SFO": "OAK"}.get(origen, origen)})

    def feed_puente(sitio, titulo, precio, origen_texto, destino_texto, error=False):
        return Tarifa(fuente="feed", sitio=sitio, origen="", origen_texto=origen_texto, destino="",
                      destino_texto=destino_texto, precio=precio, puente=True, encontrado=hace_6h,
                      link="https://www.secretflying.com/posts/ejemplo-" + origen_texto.lower().replace(" ", "-"),
                      titulo=titulo, es_error=error)

    return [
        tp("TYO", 398, 96, 9, "NH", 1),
        tp("OSA", 1080, 120, 10, "AA", 2),
        tp("HNL", 790, 75, 7, "UA", 1),
        tp("NYC", 79, 40, 4, "B6", 0),
        tp("ORL", 39, 30, 0, "NK", 0, rt=False),
        tp("PAR", 455, 150, 8, "AF", 1),
        tp("LIS", 199, 110, 7, "TP", 1),
        tp("SEL", 520, 160, 12, "KE", 1),
        tp("YTO", 410, 60, 5, "AC", 1),
        tp("BCN", 560, 90, 7, "IB", 1),
        tp("MIA", 118, 45, 5, "AA", 0),
        tp("LAX", 289, 70, 6, "AA", 1),
        tp("SFO", 310, 70, 6, "UA", 1),
        tp("CHI", 240, 70, 6, "UA", 0),
        tp("MAD", 590, 100, 7, "IB", 0),
        tp("BOG", 210, 50, 6, "B6", 0),
        feed("Secret Flying", "San Juan, Puerto Rico to London, United Kingdom for only $229 USD roundtrip (ERROR FARE)", 229, True, "London, United Kingdom"),
        feed("Secret Flying (San Juan)", "Non-stop from San Juan, Puerto Rico to Madrid, Spain for only $312 USD roundtrip", 312, False, "Madrid, Spain"),
        # Ofertas que salen de EE.UU. (para combinados)
        puente("LAX", "OSA", 262, 121, 9, "ZG", 0),
        puente("SFO", "SAP", 340, 140, 8, "UA", 1),
        feed_puente("Secret Flying", "ERROR FARE: Chicago to Honolulu, Hawaii for only $158 USD roundtrip", 158,
                    "Chicago", "Honolulu, Hawaii", error=True),
    ]


def personas_demo() -> List[dict]:
    return [
        {"id": "u1", "email": "tia@ejemplo.com", "nombre": "Carmen", "bienvenida": False,
         "token_baja": "11111111-1111-4111-8111-111111111111",
         "destinos": [{"t": "p", "c": "JP", "n": "Japón"}]},
        {"id": "u2", "email": "pana@ejemplo.com", "nombre": "Luis", "bienvenida": True,
         "token_baja": "22222222-2222-4222-8222-222222222222",
         "destinos": [{"t": "c", "c": "MAD", "n": "Madrid"}, {"t": "c", "c": "LON", "n": "Londres"},
                      {"t": "r", "c": "hawaii", "n": "Hawaii"}]},
        {"id": "u3", "email": "yo@ejemplo.com", "nombre": "J", "bienvenida": True,
         "token_baja": "33333333-3333-4333-8333-333333333333",
         "destinos": [{"t": "r", "c": "todo", "n": "Cualquier destino"}]},
    ]


class TravelpayoutsDemo:
    """Simula lo que cuesta SJU -> ciudad puente para esas fechas."""
    PRECIOS = {"LAX": 289, "SFO": 318, "CHI": 236, "NYC": 160, "MIA": 120}

    def precio_puente(self, ciudad, salida, regreso, dias_antes=1, margen=2):
        if ciudad not in self.PRECIOS or not salida:
            return None
        ida = (date.fromisoformat(salida) - timedelta(days=dias_antes)).isoformat()
        vuelta = (date.fromisoformat(regreso) + timedelta(days=dias_antes)).isoformat() if regreso else None
        t = Tarifa(fuente="travelpayouts", origen="SJU", destino=ciudad, precio=self.PRECIOS[ciudad],
                   salida=ida, regreso=vuelta, aerolinea="AA", aeropuerto={"LAX": "LAX", "SFO": "SFO", "CHI": "ORD"}.get(ciudad))
        t.extra["exacto"] = True
        return t
