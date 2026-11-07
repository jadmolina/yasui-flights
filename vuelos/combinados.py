"""Combinados ("vuelo puente").

A veces sale una oferta loca desde otra ciudad, por ejemplo Los Ángeles -> Tokio $250,
pero no desde San Juan. Aquí sumamos lo que cuesta llegar de SJU a esa ciudad y, si el
total sale bastante más barato que ir directo desde SJU, lo presentamos como oferta:

    SJU -> Los Ángeles  ~$300   +   Los Ángeles -> Tokio  $250   =   ~$550
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional

from .detector import NIVELES, Detector
from .lugares import Lugares
from .models import Tarifa
from .sources.google_flights import link_google
from .util import log


class Combinador:
    def __init__(self, config: dict, detector: Detector, lugares: Lugares, tp=None, gf=None):
        self.config = config
        self.conf = config.get("combinados", {})
        self.det = detector
        self.lugares = lugares
        self.tp = tp  # Travelpayouts (para buscar el SJU -> puente con fechas). Puede ser None.
        self.gf = gf  # Google Flights (respaldo con fechas exactas). Puede ser None.
        self.origen = config.get("origen", "SJU")
        self.nombres_puente = {p["ciudad"]: p["nombre"] for p in self.conf.get("puentes", [])}
        self.aeropuertos_puente = {p["ciudad"]: p.get("aeropuerto") or p["ciudad"] for p in self.conf.get("puentes", [])}

    def _nombre(self, codigo: str) -> str:
        if codigo in self.nombres_puente:
            return self.nombres_puente[codigo]
        info = self.lugares.ciudades.get(codigo) or {}
        return info.get("es") or info.get("name") or codigo

    def construir(self, tarifas: List[Tarifa], quiere: Callable[[Tarifa], bool]) -> List[dict]:
        if not self.conf.get("activo", True):
            return []
        ahorro_min = float(self.conf.get("ahorro_minimo", 0.25))
        maximo = int(self.conf.get("maximo_por_corrida", 20))
        dias_antes = int(self.conf.get("dias_antes", 1))
        margen = int(self.conf.get("dias_margen", 2))
        max_google = int(self.conf.get("maximo_google", 8))
        f_err = float(self.det.reglas.get("factor_error", 0.6))

        # Lo más barato directo desde SJU a cada lugar (hoy)
        directo: Dict[str, float] = {}
        for t in tarifas:
            if not t.puente and t.ida_y_vuelta and t.fuente != "feed":
                directo[t.destino] = min(directo.get(t.destino, float("inf")), t.precio)

        candidatos = []
        for t in tarifas:
            if not t.puente or not t.ida_y_vuelta or not t.origen or t.origen == self.origen:
                continue
            if t.destino in (t.origen, self.origen) or t.pais == "PR" or not quiere(t):
                continue
            if t.destino in self.nombres_puente or t.region in ("usa", "caribe"):
                continue  # para ir a Chicago o a Punta Cana no hace falta un combinado
            llegar = directo.get(t.origen)  # SJU -> ciudad puente (aprox.)
            if llegar is None:
                continue
            meta = self._meta(t)
            # "Lo normal" desde SJU: el menor entre lo de hoy, la mediana y un típico (meta x 1.8).
            # Así un precio raro de $2,000 en Aviasales no hace parecer un combinado más barato de lo que es.
            opciones = [x for x in (directo.get(t.destino), self.det.mediana(f"{t.destino}:rt"),
                                    meta * float(self.det.reglas.get("factor_tipico", 1.8))) if x]
            ref = min(opciones) if opciones else None
            total_aprox = t.precio + llegar
            prometedor = t.es_error or total_aprox <= meta * 1.15 or (ref and total_aprox <= ref * (1 - ahorro_min) * 1.1)
            if prometedor:
                candidatos.append((total_aprox / (ref or meta), t, llegar, ref, meta))

        candidatos.sort(key=lambda c: c[0])
        ofertas: Dict[str, dict] = {}
        exactos = google = sin_fechas = 0
        for _, t, llegar, ref, meta in candidatos:
            ap_tramo = (t.extra or {}).get("aeropuerto_origen") or self.aeropuertos_puente.get(t.origen) or t.origen
            p_precio = p_salida = p_regreso = p_aerolinea = p_aeropuerto = p_iata = None
            exacto = False
            if t.salida:
                # El vuelo largo tiene fechas: el SJU -> puente TIENE que cuadrar con ellas.
                if exactos >= maximo:
                    continue
                exactos += 1
                puente = None
                if self.tp is not None:
                    try:
                        puente = self.tp.precio_puente(t.origen, t.salida, t.regreso, dias_antes, margen)
                    except Exception:  # noqa: BLE001
                        puente = None
                if puente is not None and puente.precio > 0:
                    p_precio, p_salida, p_regreso = puente.precio, puente.salida, puente.regreso
                    p_aerolinea = self.lugares.nombre_aerolinea(puente.aerolinea)
                    p_iata = puente.aerolinea if puente.aerolinea and len(puente.aerolinea) == 2 else None
                    p_aeropuerto = puente.aeropuerto
                    exacto = True
                elif self.gf is not None and not getattr(self.gf, "bloqueado", False) and google < max_google:
                    google += 1
                    ida = (date.fromisoformat(t.salida) - timedelta(days=dias_antes)).isoformat()
                    vuelta = (date.fromisoformat(t.regreso) + timedelta(days=dias_antes)).isoformat() if t.regreso else None
                    res = self.gf.precio(ap_tramo, ida, vuelta, origen=self.origen)
                    if res:
                        p_precio, p_salida, p_regreso = res["precio"], ida, vuelta
                        p_aerolinea, p_aeropuerto, exacto = res.get("aerolinea"), ap_tramo, True
                        p_iata = self.lugares.iata_aerolinea(p_aerolinea)
                if p_precio is None:
                    sin_fechas += 1
                    continue  # no hay precio real para esas fechas: mejor no enseñarlo
            else:
                # Post sin fechas (feeds): solo podemos dar el precio típico SJU -> puente
                p_precio = llegar
            total = t.precio + p_precio
            o = self._evaluar(t, total, ref, meta, ahorro_min, f_err)
            if not o:
                continue
            nombre_puente = self._nombre(t.origen)
            o.update({
                "tramo": {
                    "origen": t.origen, "origen_nombre": nombre_puente, "precio": t.precio,
                    "aeropuerto_origen": (t.extra or {}).get("aeropuerto_origen") if t.salida else None,
                    "salida": t.salida, "regreso": t.regreso, "aerolinea": t.aerolinea, "escalas": t.escalas,
                    "aerolinea_iata": t.aerolinea_iata,
                    "link": t.link or link_google(t.origen, t.aeropuerto or t.destino, t.salida, t.regreso),
                    "sitio": t.sitio, "titulo": t.titulo,
                },
                "puente": {
                    "ciudad": t.origen, "nombre": nombre_puente, "precio": p_precio, "exacto": exacto,
                    "salida": p_salida, "regreso": p_regreso, "aerolinea": p_aerolinea,
                    "aerolinea_iata": p_iata, "aeropuerto": p_aeropuerto,
                    "link": link_google(self.origen, p_aeropuerto or t.origen, p_salida, p_regreso),
                },
            })
            clave = f"{t.origen}:{t.destino}:{(t.salida or '')[:7]}"
            if clave not in ofertas or o["precio"] < ofertas[clave]["precio"]:
                ofertas[clave] = o
        lista = list(ofertas.values())
        if candidatos:
            log(f"  Combinados: {len(lista)} ofertas ({len(candidatos)} candidatos; {google} revisados en Google; "
                f"{sin_fechas} descartados porque el vuelo desde SJU no cuadraba con las fechas)")
        return lista

    # ------------------------------------------------------------------
    def _meta(self, t: Tarifa) -> float:
        """La meta es la misma que si saliera de SJU a ese destino."""
        copia = Tarifa(fuente=t.fuente, origen=self.origen, destino=t.destino, precio=t.precio,
                       ida_y_vuelta=True, favorito=t.favorito)
        copia.region, copia.distancia = t.region, t.distancia
        return self.det.meta(copia)

    def _evaluar(self, t: Tarifa, total: float, ref: Optional[float], meta: float, ahorro_min: float, f_err: float) -> Optional[dict]:
        ahorro = round(1 - total / ref, 3) if ref else None
        if ref and total >= ref:
            return None  # no tiene sentido si directo sale igual o más barato
        nivel, motivos = 0, []
        if t.es_error:
            nivel = 3
            motivos.append(f"{t.sitio} reporta el vuelo desde {self._nombre(t.origen)} como error de tarifa")
        if total <= meta * f_err:
            nivel = 3
            motivos.append(f"Total menos del {int(f_err * 100)}% de tu precio meta (${meta:,.0f})")
        if ahorro is not None and ahorro >= 0.5:
            nivel = 3
            motivos.append(f"{ahorro:.0%} más barato que lo normal desde SJU (~${ref:,.0f})")
        if nivel < 3:
            if total <= meta:
                nivel = 2
                motivos.append(f"Total debajo de tu precio meta (${meta:,.0f})")
            if ahorro is not None and ahorro >= ahorro_min:
                nivel = 2
                motivos.append(f"{ahorro:.0%} más barato que lo normal desde SJU (~${ref:,.0f})")
        texto_ahorro = f"{ahorro:.0%} más barato que lo normal desde SJU (~${ref:,.0f})" if ahorro is not None else ""
        if nivel and ahorro is not None and ahorro >= ahorro_min and texto_ahorro not in motivos:
            motivos.append(texto_ahorro)
        if nivel == 0:
            return None
        base = f"combo|{t.origen}|{t.destino}|{t.salida}|{t.regreso}|{t.link if t.fuente == 'feed' else ''}"
        return {
            "id": hashlib.sha1(base.encode()).hexdigest()[:12],
            "tipo": "combinado",
            "fuente": t.fuente, "sitio": t.sitio,
            "origen": self.origen, "destino": t.destino, "destino_nombre": t.destino_nombre,
            "pais": t.pais, "pais_nombre": t.pais_nombre, "region": t.region, "aeropuerto": t.aeropuerto,
            "precio": round(total), "ida_y_vuelta": True, "salida": t.salida, "regreso": t.regreso,
            "aerolinea": t.aerolinea, "aerolinea_iata": t.aerolinea_iata, "escalas": t.escalas,
            "titulo": t.titulo, "es_error": t.es_error,
            "encontrado": t.encontrado, "link": t.link,
            "nivel": nivel, "nivel_nombre": NIVELES[nivel], "motivos": motivos,
            "meta": meta, "mediana": ref, "descuento": ahorro, "directo": ref,
            "verificado": None, "precio_google": None,
            "primera_vez": self.det.corrida, "ultima_vez": self.det.corrida,
            "link_google": link_google(t.origen, t.aeropuerto or t.destino, t.salida, t.regreso),
        }
