"""Google Flights usando la librería fast-flights (no necesita API key).

Dos usos:
  1. escanear(): prueba fechas al azar en tus destinos favoritos.
  2. verificar(): confirma el precio real de una oferta que encontró otra fuente.

Google puede bloquear si se hacen muchas búsquedas seguidas, por eso hay
pausas y un límite por corrida (config.yaml -> google_flights).
"""
from __future__ import annotations

import random
import time
from datetime import date, timedelta
from typing import List, Optional
from urllib.parse import quote

from ..models import Tarifa
from ..util import aviso, log, ahora_iso

try:  # fast-flights 3.x necesita Python 3.10+
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    DISPONIBLE = True
except Exception:  # noqa: BLE001
    DISPONIBLE = False


def link_google(origen: str, destino: str, salida: Optional[str] = None, regreso: Optional[str] = None) -> str:
    texto = f"Flights to {destino} from {origen}"
    if salida:
        texto += f" on {salida}"
        if regreso:
            texto += f" through {regreso}"
        else:
            texto += " one way"
    return f"https://www.google.com/travel/flights?q={quote(texto)}&hl=es&curr=USD"


class GoogleFlights:
    nombre = "Google Flights"

    def __init__(self, config: dict):
        self.config = config
        self.conf = config.get("google_flights", {})
        self.origen = config.get("origen", "SJU")
        self.busquedas = 0
        self.fallos_seguidos = 0
        self.errores: List[str] = []
        self.bloqueado = False

    # -------------------------------------------------------------- básico
    def precio(self, destino: str, salida: str, regreso: Optional[str]) -> Optional[dict]:
        """Precio más barato en Google Flights para esas fechas, o None."""
        if not DISPONIBLE or self.bloqueado:
            return None
        vuelos = [FlightQuery(date=salida, from_airport=self.origen, to_airport=destino)]
        if regreso:
            vuelos.append(FlightQuery(date=regreso, from_airport=destino, to_airport=self.origen))
        q = create_query(
            flights=vuelos,
            trip="round-trip" if regreso else "one-way",
            seat="economy",
            passengers=Passengers(adults=1),
            language="en-US",
            currency="USD",
        )
        self.busquedas += 1
        try:
            resultados = get_flights(q)
            self.fallos_seguidos = 0
        except Exception as e:  # noqa: BLE001
            nombre = type(e).__name__
            if nombre != "FlightsNotFound":
                self.fallos_seguidos += 1
                self.errores.append(f"{destino} {salida}: {nombre}: {e}"[:200])
                if self.fallos_seguidos >= 3:
                    self.bloqueado = True
                    aviso("Google Flights falló 3 veces seguidas; lo pauso por esta corrida.")
            return None
        finally:
            time.sleep(random.uniform(2.0, 4.0))
        validos = [f for f in resultados if getattr(f, "price", 0) and f.price > 0]
        if not validos:
            return None
        mejor = min(validos, key=lambda f: f.price)
        return {
            "precio": float(mejor.price),
            "aerolinea": ", ".join(mejor.airlines[:2]) if mejor.airlines else None,
            "escalas": max(0, len(mejor.flights) - 1),
        }

    # -------------------------------------------------------------- escaneo
    def escanear(self, extra: Optional[List[str]] = None) -> List[Tarifa]:
        """Prueba fechas al azar en los destinos base y en los que escogió la gente (extra)."""
        if not DISPONIBLE:
            aviso("fast-flights no está instalado (necesita Python 3.10+). Me salto Google Flights.")
            return []
        favoritos = [f for f in self.config.get("favoritos", []) if f.get("aeropuerto")]
        ya = {f["ciudad"] for f in favoritos}
        favoritos += [{"ciudad": c, "aeropuerto": c} for c in (extra or []) if c not in ya]
        n = int(self.conf.get("busquedas_por_corrida", 10))
        dias_min = int(self.conf.get("dias_minimos", 14))
        dias_max = int(self.conf.get("dias_maximos", 270))
        duraciones = self.conf.get("dias_de_viaje", [5, 7, 10])
        random.shuffle(favoritos)
        tarifas: List[Tarifa] = []
        for fav in favoritos[:n]:
            if self.bloqueado:
                break
            salida_d = date.today() + timedelta(days=random.randint(dias_min, dias_max))
            regreso_d = salida_d + timedelta(days=int(random.choice(duraciones)))
            salida, regreso = salida_d.isoformat(), regreso_d.isoformat()
            res = self.precio(fav["aeropuerto"], salida, regreso)
            if not res:
                continue
            tarifas.append(Tarifa(
                fuente="google", sitio="Google Flights", origen=self.origen, destino=fav["aeropuerto"],
                precio=res["precio"], ida_y_vuelta=True, salida=salida, regreso=regreso,
                aerolinea=res["aerolinea"], escalas=res["escalas"],
                link=link_google(self.origen, fav["aeropuerto"], salida, regreso), encontrado=ahora_iso(),
            ))
        log(f"  Google Flights: {len(tarifas)} precios ({self.busquedas} búsquedas)")
        return tarifas

    # -------------------------------------------------------------- verificar
    def verificar(self, ofertas: List[dict]) -> int:
        """Confirma en Google las mejores ofertas que no vienen de Google. Devuelve cuántas revisó."""
        if not DISPONIBLE:
            return 0
        limite = int(self.conf.get("verificar_ofertas", 8))
        revisadas = 0
        candidatas = [
            o for o in ofertas
            if o["fuente"] == "travelpayouts" and o.get("tipo") != "combinado"
            and o.get("salida") and o.get("verificado") is None
        ]
        candidatas.sort(key=lambda o: (-o["nivel"], -(o.get("descuento") or 0)))
        for o in candidatas[:limite]:
            if self.bloqueado:
                break
            destino = o.get("aeropuerto") or o["destino"]
            res = self.precio(destino, o["salida"], o.get("regreso") if o["ida_y_vuelta"] else None)
            revisadas += 1
            if not res:
                continue
            o["precio_google"] = res["precio"]
            o["verificado_en"] = ahora_iso()
            # Confirmado si Google lo tiene a no más de 15% por encima
            o["verificado"] = res["precio"] <= o["precio"] * 1.15
        return revisadas
