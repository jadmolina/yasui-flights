"""Travelpayouts / Aviasales Data API.

Precios más baratos que la gente ha encontrado en Aviasales en los últimos
días (vienen de cache, por eso se confirman luego en Google Flights).
Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Iterable, List, Optional

from ..models import Tarifa
from ..util import aviso, log, sesion_http, ahora_iso

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def _meses(n: int) -> Iterable[str]:
    hoy = date.today()
    y, m = hoy.year, hoy.month
    for _ in range(n):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


class Travelpayouts:
    nombre = "Travelpayouts"

    def __init__(self, token: str, config: dict):
        self.token = token
        self.config = config
        self.origen = config.get("origen", "SJU")
        self.http = sesion_http()
        self.http.headers["X-Access-Token"] = token
        self.llamadas = 0
        self.errores: List[str] = []

    def _get(self, **params) -> list:
        base = {"currency": "usd", "market": "us", "sorting": "price", "limit": 1000, "origin": self.origen}
        base.update({k: v for k, v in params.items() if v is not None})
        for intento in range(3):
            try:
                self.llamadas += 1
                r = self.http.get(API, params=base, timeout=30)
                if r.status_code == 429:
                    time.sleep(5 * (intento + 1))
                    continue
                if r.status_code in (401, 403):
                    raise RuntimeError("token inválido o sin permiso (revisa TRAVELPAYOUTS_TOKEN)")
                r.raise_for_status()
                datos = r.json()
                if not datos.get("success", True):
                    raise RuntimeError(datos.get("error") or "respuesta sin éxito")
                time.sleep(0.4)
                return datos.get("data") or []
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                if intento == 2:
                    self.errores.append(str(e))
                    return []
                time.sleep(2)
        return []

    def _convertir(self, fila: dict, ida_y_vuelta: bool, puente: bool = False) -> Tarifa:
        link = fila.get("link") or ""
        if link and not link.startswith("http"):
            link = "https://www.aviasales.com/" + link.lstrip("/")
        salida = (fila.get("departure_at") or "")[:10] or None
        regreso = (fila.get("return_at") or "")[:10] or None
        escalas = fila.get("transfers")
        if ida_y_vuelta and fila.get("return_transfers") is not None and escalas is not None:
            escalas = max(escalas, fila["return_transfers"])
        return Tarifa(
            fuente="travelpayouts",
            sitio="Aviasales",
            origen=fila.get("origin") or self.origen,
            destino=fila.get("destination") or fila.get("destination_airport"),
            precio=float(fila.get("price") or 0),
            ida_y_vuelta=ida_y_vuelta and bool(regreso),
            salida=salida,
            regreso=regreso if ida_y_vuelta else None,
            aerolinea=fila.get("airline"),
            escalas=escalas,
            link=link or None,
            encontrado=ahora_iso(),
            aeropuerto=fila.get("destination_airport"),
            puente=puente,
            extra={"vuelo": fila.get("flight_number"), "duracion_min": fila.get("duration"),
                   "aeropuerto_origen": fila.get("origin_airport")},
        )

    def buscar(self, destinos_extra: Iterable[str] = ()) -> List[Tarifa]:
        """Todo lo que sale de SJU: "a donde sea" + destinos base + destinos que escogió la gente."""
        conf = self.config.get("travelpayouts", {})
        meses = int(conf.get("meses_a_buscar", 8))
        maximo = int(conf.get("maximo_destinos", 70))
        tarifas: List[Tarifa] = []

        # 1) "A donde sea": lo más barato a cada destino, mes por mes (ida y vuelta)
        for mes in _meses(meses):
            for fila in self._get(departure_at=mes, one_way="false", unique="true"):
                tarifas.append(self._convertir(fila, True))
        # ...y sin fecha fija
        for fila in self._get(one_way="false", unique="true"):
            tarifas.append(self._convertir(fila, True))
        # 2) "A donde sea" solo ida
        for fila in self._get(one_way="true", unique="true"):
            tarifas.append(self._convertir(fila, False))

        # 3) Destino por destino: primero los que escogió la gente, después los base
        codigos: List[str] = []
        for c in list(destinos_extra) + [f["ciudad"] for f in self.config.get("favoritos", [])]:
            if c and c != self.origen and c not in codigos:
                codigos.append(c)
        for codigo in codigos[:maximo]:
            for fila in self._get(destination=codigo, one_way="false", limit=10):
                tarifas.append(self._convertir(fila, True))

        tarifas = [t for t in tarifas if t.precio > 0 and t.destino and t.destino != self.origen]
        log(f"  Travelpayouts: {len(tarifas)} precios desde {self.origen} ({self.llamadas} llamadas, "
            f"{min(len(codigos), maximo)} destinos uno por uno)")
        if self.errores:
            aviso(f"Travelpayouts tuvo {len(self.errores)} errores. Último: {self.errores[-1]}")
        return tarifas

    def buscar_puentes(self, puentes: List[dict]) -> List[Tarifa]:
        """Lo más barato a cada destino saliendo de ciudades grandes de EE.UU. (ida y vuelta)."""
        antes = self.llamadas
        tarifas: List[Tarifa] = []
        for p in puentes:
            for fila in self._get(origin=p["ciudad"], one_way="false", unique="true"):
                t = self._convertir(fila, True, puente=True)
                t.origen = p["ciudad"]
                if t.precio > 0 and t.destino and t.destino not in (p["ciudad"], self.origen):
                    tarifas.append(t)
        log(f"  Travelpayouts (ciudades puente): {len(tarifas)} precios ({self.llamadas - antes} llamadas)")
        return tarifas

    def precio_puente(self, ciudad: str, salida: Optional[str], regreso: Optional[str], dias_antes: int = 1) -> Optional[Tarifa]:
        """Lo más barato SJU -> ciudad puente para llegar antes del vuelo y volver después.
        Primero prueba las fechas exactas; si no hay datos, el mes."""
        intentos = []
        if salida:
            ida = (date.fromisoformat(salida) - timedelta(days=dias_antes)).isoformat()
            vuelta = (date.fromisoformat(regreso) + timedelta(days=dias_antes)).isoformat() if regreso else None
            intentos.append((ida, vuelta, True))
            intentos.append((ida[:7], vuelta[:7] if vuelta else None, False))
        for ida, vuelta, exacto in intentos:
            filas = self._get(destination=ciudad, departure_at=ida, return_at=vuelta,
                              one_way="false" if vuelta else "true", limit=5)
            if filas:
                t = self._convertir(sorted(filas, key=lambda f: f.get("price") or 1e9)[0], bool(vuelta))
                t.extra["exacto"] = exacto
                return t
        return None
