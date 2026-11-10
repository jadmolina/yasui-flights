"""Travelpayouts / Aviasales Data API.

Precios más baratos que la gente ha encontrado en Aviasales en los últimos
días (vienen de cache, por eso se confirman luego en Google Flights).
Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional

from ..models import Tarifa
from ..util import aviso, log, sesion_http, ahora_iso

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def _dt(texto: Optional[str]) -> Optional[datetime]:
    """'2026-12-10T06:15:00-04:00' -> datetime con zona horaria (None si no se puede)."""
    if not texto or "T" not in texto:
        return None
    try:
        v = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return v if v.tzinfo else None


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
                   "aeropuerto_origen": fila.get("origin_airport"),
                   # horas exactas (con zona horaria) y duración de cada dirección: sirven para
                   # saber a qué hora llegas y si da tiempo de conectar el mismo día
                   "sale_at": fila.get("departure_at"), "regresa_at": fila.get("return_at") if ida_y_vuelta else None,
                   "dur_ida": fila.get("duration_to"), "dur_vuelta": fila.get("duration_back")},
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

    def buscar_desde(self, origen: str, meses: int = 8) -> List[Tarifa]:
        """Búsqueda más ligera desde otro aeropuerto de PR (Aguadilla): solo "a donde sea"."""
        antes = self.llamadas
        tarifas: List[Tarifa] = []
        filas = []
        for mes in _meses(meses):
            filas += [(f, True) for f in self._get(origin=origen, departure_at=mes, one_way="false", unique="true")]
        filas += [(f, True) for f in self._get(origin=origen, one_way="false", unique="true")]
        filas += [(f, False) for f in self._get(origin=origen, one_way="true", unique="true")]
        for fila, rt in filas:
            t = self._convertir(fila, rt)
            t.origen, t.alterno = origen, True
            if t.precio > 0 and t.destino and t.destino not in (origen, self.origen):
                tarifas.append(t)
        log(f"  Travelpayouts desde {origen}: {len(tarifas)} precios ({self.llamadas - antes} llamadas)")
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

    def precio_puente(self, ciudad: str, salida: Optional[str], regreso: Optional[str],
                      dias_antes: int = 1, margen: int = 2, horas: Optional[dict] = None,
                      castigo_mismo_dia: float = 40) -> Optional[Tarifa]:
        """Lo más barato SJU -> ciudad puente que CUADRE con el otro vuelo:
        salir entre (salida - dias_antes - margen) y (salida - dias_antes),
        y regresar entre (regreso + dias_antes) y (regreso + dias_antes + margen).

        Si sabemos las horas del otro vuelo (`horas`), también vale conectar el MISMO DÍA cuando hay
        por lo menos horas["min_ida"] / horas["min_vuelta"] minutos entre un avión y el otro, en el mismo
        aeropuerto. Se prefiere llegar el día antes, a menos que el mismo día ahorre `castigo_mismo_dia`.
          horas = {"sale": datetime del vuelo largo, "aeropuerto": de dónde sale,
                   "vuelve_llega": datetime en que llega de vuelta a la ciudad puente (o None),
                   "min_ida": 60, "min_vuelta": 60}
        Si Aviasales no tiene nada que cuadre, devuelve None (no se inventa un precio)."""
        if not salida:
            return None
        horas = horas or {}
        d = date.fromisoformat(salida)
        r = date.fromisoformat(regreso) if regreso else None
        ida_max = d - timedelta(days=dias_antes)
        ida_min = ida_max - timedelta(days=margen)
        vuelta_min = r + timedelta(days=dias_antes) if r else None
        vuelta_max = vuelta_min + timedelta(days=margen) if vuelta_min else None
        ap = horas.get("aeropuerto")
        medio_dia = 12 * 60  # menos de 12 h entre los dos aviones = "mismo día"

        def conexion(llega: datetime, sale: datetime, aeropuerto) -> dict:
            return {"aeropuerto": aeropuerto, "llega": llega.astimezone(sale.tzinfo).isoformat(timespec="minutes"),
                    "sale": sale.isoformat(timespec="minutes"), "minutos": int((sale - llega).total_seconds() // 60)}

        def revisar(f: dict) -> Optional[dict]:
            """None si no cuadra. Si cuadra: {"ida": conexión del mismo día o None, "vuelta": ...}"""
            sale = _dt(f.get("departure_at"))
            if sale is None:
                return None
            mismo_ap = bool(ap and f.get("destination_airport") and f["destination_airport"] == ap)
            con = {"ida": None, "vuelta": None}
            # ---- ida (SJU -> puente)
            if not (ida_min <= sale.date() <= d):
                return None
            if horas.get("sale") and f.get("duration_to"):
                llega = sale + timedelta(minutes=int(f["duration_to"]))
                c = conexion(llega, horas["sale"], f.get("destination_airport"))
                if c["minutos"] < int(horas.get("min_ida", 60)):
                    return None
                if c["minutos"] < medio_dia:
                    if not mismo_ap:
                        return None  # cambiar de aeropuerto el mismo día con boletos separados: no
                    con["ida"] = c
            elif sale.date() > ida_max:
                return None  # sin horas no podemos saber si da tiempo el mismo día
            if not r:
                return con
            # ---- vuelta (puente -> SJU)
            vuelve = _dt(f.get("return_at"))
            if vuelve is None or not (r <= vuelve.date() <= vuelta_max):
                return None
            if horas.get("vuelve_llega"):
                c = conexion(horas["vuelve_llega"], vuelve, f.get("destination_airport"))
                if c["minutos"] < int(horas.get("min_vuelta", 60)):
                    return None
                if c["minutos"] < medio_dia:
                    if not mismo_ap:
                        return None
                    con["vuelta"] = c
            elif vuelve.date() < vuelta_min:
                return None
            return con

        rt = "false" if r else "true"
        buenas: List[tuple] = []

        def probar(filas: list) -> None:
            for f in filas:
                con = revisar(f)
                if con is not None:
                    buenas.append((f, con))

        # 1) fechas exactas: un día antes / un día después
        probar(self._get(destination=ciudad, departure_at=ida_max.isoformat(),
                         return_at=vuelta_min.isoformat() if vuelta_min else None, one_way=rt, limit=10))
        # 2) el mismo día (solo si sabemos a qué hora sale el otro vuelo)
        if horas.get("sale"):
            vuelta_md = (r if horas.get("vuelve_llega") else vuelta_min) if r else None
            probar(self._get(destination=ciudad, departure_at=d.isoformat(),
                             return_at=vuelta_md.isoformat() if vuelta_md else None, one_way=rt, limit=10))
        # 3) todo el mes (o los dos meses) y nos quedamos con lo que cuadre
        if not buenas:
            for mes in sorted({ida_min.strftime("%Y-%m"), d.strftime("%Y-%m")}):
                probar(self._get(destination=ciudad, departure_at=mes, one_way=rt, limit=1000))
        if not buenas:
            return None

        def costo(par) -> float:
            f, con = par
            return float(f.get("price") or 1e9) + (castigo_mismo_dia if (con["ida"] or con["vuelta"]) else 0)

        fila, con = min(buenas, key=costo)
        t = self._convertir(fila, bool(r))
        t.extra["exacto"] = True
        t.extra["conexion"] = con if (con["ida"] or con["vuelta"]) else None
        return t
