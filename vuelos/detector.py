"""Decide qué es una oferta, guarda el historial de precios y evita repetir emails.

Niveles:
  3 = Posible error de tarifa (mistake fare)
  2 = Ganga
  1 = Oferta publicada por un sitio de ofertas (no tan extrema)
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional

from .lugares import Lugares
from .models import Tarifa
from .sources.google_flights import link_google
from .util import DATA, ahora_iso, guardar_json, horas_desde, hoy_pr, leer_json

NIVELES = {3: "Posible error de tarifa", 2: "Ganga", 1: "Oferta"}
VERSION_REGLAS = 3  # si cambian las reglas, las ofertas viejas se descartan en vez de arrastrarse

ARCH_HISTORIAL = DATA / "historial.json"
ARCH_OFERTAS = DATA / "ofertas.json"
ARCH_AVISADOS = DATA / "avisados.json"


def coincide(o: dict, destinos: list) -> bool:
    """¿Esta oferta le interesa a alguien que escogió estos destinos?
    destinos: [{"t": "c"|"p"|"r", "c": código}]  c=ciudad, p=país, r=región
    ('*' = cualquier error de tarifa, 'todo' = lo más barato a cualquier destino)."""
    for d in destinos or []:
        tipo, codigo = d.get("t"), d.get("c")
        if tipo == "c" and codigo in (o.get("destino"), o.get("aeropuerto")):
            return True
        if tipo == "p" and codigo == o.get("pais"):
            return True
        if tipo == "r" and (codigo == o.get("region") or codigo == "todo"
                            or (codigo == "*" and (o.get("nivel") or 0) >= 3)):
            return True
    return False


def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", texto or "").strip("-").upper()[:24] or "X"


class Detector:
    def __init__(self, config: dict, lugares: Lugares, carpeta=None):
        self.config = config
        self.lugares = lugares
        self.reglas = config.get("reglas", {})
        self.metas = config.get("metas_por_region", {})
        self.carpeta = carpeta or DATA
        self.historial: Dict[str, Dict[str, float]] = leer_json(self.carpeta / ARCH_HISTORIAL.name, {})
        self.avisados: Dict[str, dict] = leer_json(self.carpeta / ARCH_AVISADOS.name, {})
        self.previas: List[dict] = leer_json(self.carpeta / ARCH_OFERTAS.name, [])
        self.corrida = ahora_iso()
        self.hoy = hoy_pr()
        self.elegidos: set = set()  # ciudades que alguien escogió en la página (se tratan como favoritos)

    # ============================================================ preparar
    def preparar(self, tarifas: List[Tarifa]) -> List[Tarifa]:
        """Completa nombres/regiones y resuelve el destino de los posts de feeds."""
        listas = []
        for t in tarifas:
            if t.fuente == "feed" and t.puente and not t.origen:
                # Post que sale de otra ciudad (p. ej. "Los Angeles to Tokyo"): necesitamos saber de cuál
                t.origen = self.lugares.buscar_por_texto(t.origen_texto or "") or ""
                if not t.origen:
                    continue
            if t.fuente == "feed" and not t.destino:
                codigo = self.lugares.buscar_por_texto(t.destino_texto or "")
                if codigo:
                    t.destino = codigo
                else:
                    t.destino = _slug(t.destino_texto)
                    t.destino_nombre = (t.destino_texto or "").split(",")[0].strip() or t.destino_texto
                    t.pais = self.lugares.pais_por_texto(t.destino_texto or "")
            listas.append(self.lugares.enriquecer(t))
        return listas

    # ============================================================ historial
    def actualizar_historial(self, tarifas: List[Tarifa]) -> None:
        minimos: Dict[str, float] = {}
        for t in tarifas:
            if t.fuente == "feed" or t.puente:
                continue
            k = t.clave_ruta()
            minimos[k] = min(minimos.get(k, float("inf")), t.precio)
        for k, precio in minimos.items():
            serie = self.historial.setdefault(k, {})
            serie[self.hoy] = min(serie.get(self.hoy, float("inf")), precio)
        limite = (date.fromisoformat(self.hoy) - timedelta(days=120)).isoformat()
        for k in list(self.historial):
            self.historial[k] = {d: p for d, p in self.historial[k].items() if d >= limite}
            if not self.historial[k]:
                del self.historial[k]

    def mediana(self, clave: str) -> Optional[float]:
        serie = self.historial.get(clave, {})
        limite = (date.fromisoformat(self.hoy) - timedelta(days=90)).isoformat()
        valores = [p for d, p in serie.items() if limite <= d < self.hoy]
        if len(valores) < int(self.reglas.get("dias_minimos_historial", 4)):
            return None
        return round(statistics.median(valores))

    # ============================================================ evaluar
    def meta(self, t: Tarifa) -> float:
        fav = self.lugares.favoritos.get(t.destino) if t.favorito else None
        if fav and fav.get("meta"):
            meta = float(fav["meta"])
        else:
            meta = float(self.metas.get(t.region or "otros", self.metas.get("otros", 600)))
            if not t.favorito and t.destino not in self.elegidos and t.distancia and t.distancia >= 1500:
                por_milla = float(self.reglas.get("centavos_por_milla", 3.5)) / 100 * t.distancia * 2
                meta = min(meta, por_milla)
        if not t.ida_y_vuelta:
            meta *= float(self.reglas.get("factor_solo_ida", 0.55))
        return round(meta)

    def evaluar(self, t: Tarifa) -> Optional[dict]:
        meta = self.meta(t)
        mediana = self.mediana(t.clave_ruta())
        descuento = round(1 - t.precio / mediana, 3) if mediana else None
        f_err = float(self.reglas.get("factor_error", 0.6))
        d_err = float(self.reglas.get("descuento_error", 0.5))
        d_gan = float(self.reglas.get("descuento_ganga", 0.35))

        nivel, motivos = 0, []
        if t.fuente == "feed" and not t.pais and not t.favorito:
            # No sabemos bien a dónde es: no le aplicamos las metas, solo lo que diga el sitio
            meta, descuento, mediana = None, None, None
            nivel = 3 if t.es_error else 1
            motivos.append(f"{t.sitio} lo reporta como error de tarifa" if t.es_error else f"Publicado por {t.sitio}")
            return self._oferta(t, nivel, motivos, meta, mediana, descuento)
        if t.es_error:
            nivel = 3
            motivos.append(f"{t.sitio} lo reporta como error de tarifa")
        largo = (t.distancia or 0) >= float(self.reglas.get("millas_minimas_error", 2000))
        if t.precio <= meta * f_err and largo:
            nivel = 3
            motivos.append(f"Menos del {int(f_err * 100)}% de tu precio meta (${meta:,.0f})")
        if descuento is not None and descuento >= d_err:
            nivel = 3
            motivos.append(f"{descuento:.0%} más barato que lo normal (~${mediana:,.0f})")
        if t.precio <= meta:
            nivel = max(nivel, 2)
            if nivel == 2:
                motivos.append(f"Debajo de tu precio meta (${meta:,.0f})")
        if descuento is not None and d_gan <= descuento < d_err:
            nivel = max(nivel, 2)
            motivos.append(f"{descuento:.0%} más barato que lo normal (~${mediana:,.0f})")
        if t.fuente == "feed" and nivel < 2:
            if t.precio <= meta * 1.2:
                nivel = 2
                motivos.append(f"Publicado por {t.sitio} y cerca de tu meta (${meta:,.0f})")
            else:
                nivel = 1
                motivos.append(f"Publicado por {t.sitio}")
        if nivel == 0:
            return None
        return self._oferta(t, nivel, motivos, meta, mediana, descuento)

    def _oferta(self, t: Tarifa, nivel: int, motivos: List[str], meta, mediana, descuento) -> dict:
        o = t.to_dict()
        o.pop("extra", None)
        o.update({
            "id": t.clave_unica(),
            "nivel": nivel,
            "nivel_nombre": NIVELES[nivel],
            "motivos": motivos,
            "meta": meta,
            "mediana": mediana,
            "descuento": descuento,
            "verificado": None,
            "precio_google": None,
            "primera_vez": self.corrida,
            "ultima_vez": self.corrida,
            "link_google": link_google(t.origen, t.aeropuerto or (t.destino if len(t.destino) <= 4 else (t.destino_texto or t.destino)),
                                       t.salida, t.regreso),
            "centavos_milla": round(t.precio / (t.distancia * (2 if t.ida_y_vuelta else 1)) * 100, 1)
            if t.distancia and t.distancia > 300 else None,
        })
        if t.fuente == "google":
            o["verificado"] = True
            o["precio_google"] = t.precio
        return o

    def evaluar_todas(self, tarifas: List[Tarifa]) -> List[dict]:
        ofertas = [o for o in (self.evaluar(t) for t in tarifas if not t.puente) if o]
        # Para no llenar la página: la más barata por destino + tipo de viaje + mes
        mejores: Dict[str, dict] = {}
        for o in ofertas:
            if o["fuente"] == "feed":
                k = o["id"]
            else:
                k = f"{o['destino']}:{o['ida_y_vuelta']}:{(o.get('salida') or '')[:7]}"
            if k not in mejores or o["precio"] < mejores[k]["precio"]:
                mejores[k] = o
        # ...y máximo 2 fechas por destino (las mejores)
        por_destino: Dict[str, List[dict]] = {}
        for o in sorted(mejores.values(), key=lambda o: (-o["nivel"], -(o.get("descuento") or 0), o["precio"])):
            k = o["id"] if o["fuente"] == "feed" else f"{o['destino']}:{o['ida_y_vuelta']}"
            if len(por_destino.setdefault(k, [])) < 2:
                por_destino[k].append(o)
        return [o for lista in por_destino.values() for o in lista]

    # ============================================================ combinar con lo anterior
    def combinar(self, nuevas: List[dict]) -> List[dict]:
        previas = {o["id"]: o for o in self.previas}
        resultado: Dict[str, dict] = {}
        for o in nuevas:
            p = previas.get(o["id"])
            if p:
                o["primera_vez"] = p.get("primera_vez", o["primera_vez"])
                misma = abs(p.get("precio", 0) - o["precio"]) < 1
                if o["verificado"] is None and misma and p.get("verificado") is not None and horas_desde(p.get("verificado_en")) < 24:
                    o["verificado"] = p["verificado"]
                    o["precio_google"] = p.get("precio_google")
                    o["verificado_en"] = p.get("verificado_en")
            resultado[o["id"]] = o
        dias_feed = float(self.config.get("feeds", {}).get("dias_a_mostrar", 10))
        for oid, p in previas.items():
            if oid in resultado or p.get("v") != VERSION_REGLAS:
                continue
            if p["fuente"] == "feed":
                vigente = horas_desde(p.get("encontrado") or p.get("primera_vez")) < dias_feed * 24
            else:
                vigente = horas_desde(p.get("ultima_vez")) < 30
            if p.get("salida") and p["salida"] < self.hoy:
                vigente = False
            if vigente:
                resultado[oid] = p
        lista = list(resultado.values())
        for o in lista:
            o["v"] = VERSION_REGLAS
        lista.sort(key=lambda o: (-o["nivel"], -(o.get("descuento") or 0), o["precio"]))
        return lista

    @staticmethod
    def quitar_no_confirmadas(ofertas: List[dict]) -> List[dict]:
        """Si Google Flights tiene esas mismas fechas bastante más caras, el precio de Aviasales
        era viejo: no la enseñamos."""
        return [o for o in ofertas if o.get("verificado") is not False]

    # ============================================================ emails
    def clave_aviso(self, o: dict) -> str:
        if o.get("tipo") == "combinado":
            return f"combo:{o['tramo']['origen']}:{o['destino']}"
        if o["fuente"] == "feed":
            return "feed:" + o["id"]
        # Una alerta por destino (no por mes) para no recibir 5 emails de Tokio
        return f"{o['destino']}:{'rt' if o['ida_y_vuelta'] else 'ow'}"

    def por_avisar(self, ofertas: List[dict], destinos: Optional[list] = None,
                   avisados: Optional[Dict[str, dict]] = None, solo_nuevas: bool = True) -> List[dict]:
        """Ofertas que hay que mandarle a una persona.
        destinos: lo que escogió (None o [] = todo). avisados: lo que ya se le mandó."""
        conf = self.config.get("email", {})
        minimo = int(conf.get("nivel_minimo", 2))
        dias = float(conf.get("dias_para_repetir", 14))
        bajada = float(conf.get("bajada_para_repetir", 0.10))
        avisados = self.avisados if avisados is None else avisados
        elegidas: Dict[str, dict] = {}
        for o in ofertas:
            if o["nivel"] < minimo or (solo_nuevas and o.get("ultima_vez") != self.corrida):
                continue
            if o.get("verificado") is False:
                continue  # Google dice que ya no está a ese precio
            if destinos and not coincide(o, destinos):
                continue
            k = self.clave_aviso(o)
            prev = avisados.get(k)
            if prev and horas_desde(prev.get("fecha")) < dias * 24 and o["precio"] > prev["precio"] * (1 - bajada):
                continue
            if k not in elegidas or o["precio"] < elegidas[k]["precio"]:
                elegidas[k] = o
        lista = list(elegidas.values())
        lista.sort(key=lambda o: (-o["nivel"], -(o.get("descuento") or 0), o["precio"]))
        return lista

    def marcar_avisados(self, ofertas: List[dict], avisados: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
        destino = self.avisados if avisados is None else avisados
        for o in ofertas:
            destino[self.clave_aviso(o)] = {"precio": o["precio"], "fecha": self.corrida}
        limpio = {k: v for k, v in destino.items() if horas_desde(v.get("fecha")) < 24 * 60}
        if avisados is None:
            self.avisados = limpio
        return limpio

    # ============================================================ precios de hoy (para la página)
    def precios_mapa(self, tarifas: List[Tarifa]) -> Dict[str, dict]:
        """Precio más bajo (ida y vuelta desde SJU) por destino: lo de hoy, o lo último que se vio."""
        mapa: Dict[str, dict] = {}
        for t in tarifas:
            if t.puente or not t.ida_y_vuelta or t.fuente == "feed":
                continue
            actual = mapa.get(t.destino)
            if actual is None or t.precio < actual["precio"]:
                mapa[t.destino] = {
                    "precio": t.precio, "fecha": self.hoy, "salida": t.salida, "regreso": t.regreso,
                    "aerolinea": t.aerolinea, "aerolinea_iata": t.aerolinea_iata,
                    "nombre": t.destino_nombre, "pais": t.pais, "region": t.region,
                    "link": link_google(t.origen, t.aeropuerto or t.destino, t.salida, t.regreso),
                }
        for clave, serie in self.historial.items():
            if not clave.endswith(":rt") or ">" in clave or not serie:
                continue
            codigo = clave[:-3]
            if codigo not in mapa:
                ultimo = max(serie)
                info = self.lugares.ciudades.get(codigo, {})
                mapa[codigo] = {"precio": serie[ultimo], "fecha": ultimo, "nombre": info.get("es") or info.get("name") or codigo,
                                "pais": info.get("country"),
                                "link": link_google(self.config.get("origen", "SJU"), codigo)}
        for codigo, fila in mapa.items():
            fila["mediana"] = self.mediana(f"{codigo}:rt")
        return mapa

    # ============================================================ radar de favoritos
    def radar(self, tarifas: List[Tarifa]) -> List[dict]:
        filas = []
        for fav in self.config.get("favoritos", []):
            codigo = fav["ciudad"]
            de_hoy = [t for t in tarifas if t.destino == codigo and t.ida_y_vuelta and t.fuente != "feed"]
            mejor = min(de_hoy, key=lambda t: t.precio) if de_hoy else None
            serie = self.historial.get(f"{codigo}:rt", {})
            ultimo_dia = max(serie) if serie else None
            t_meta = Tarifa(fuente="radar", origen=self.config.get("origen", "SJU"), destino=codigo, precio=0, favorito=True)
            t_meta.region = fav.get("region")
            filas.append({
                "nombre": fav["nombre"],
                "ciudad": codigo,
                "aeropuerto": fav.get("aeropuerto"),
                "region": fav.get("region"),
                "meta": self.meta(t_meta),
                "precio": mejor.precio if mejor else (serie.get(ultimo_dia) if ultimo_dia else None),
                "precio_fecha": self.hoy if mejor else ultimo_dia,
                "salida": mejor.salida if mejor else None,
                "regreso": mejor.regreso if mejor else None,
                "aerolinea": mejor.aerolinea if mejor else None,
                "fuente": mejor.sitio if mejor else None,
                "mediana": self.mediana(f"{codigo}:rt"),
                "dias_historial": len(serie),
                "tendencia": [serie[d] for d in sorted(serie)][-30:],
                "link": link_google(self.config.get("origen", "SJU"), fav.get("aeropuerto") or codigo,
                                    mejor.salida if mejor else None, mejor.regreso if mejor else None),
            })
        return filas

    # ============================================================ guardar
    def guardar(self, ofertas: List[dict]) -> None:
        guardar_json(self.carpeta / ARCH_OFERTAS.name, ofertas)
        guardar_json(self.carpeta / ARCH_AVISADOS.name, self.avisados)
        # historial: una ruta por línea para que los cambios en git sean legibles
        ruta = self.carpeta / ARCH_HISTORIAL.name
        ruta.parent.mkdir(parents=True, exist_ok=True)
        lineas = [f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))}" for k, v in sorted(self.historial.items())]
        ruta.write_text("{\n" + ",\n".join(lineas) + "\n}\n", encoding="utf-8")
