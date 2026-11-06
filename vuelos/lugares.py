"""Nombres de ciudades, países, regiones y distancias.

Usa los datos públicos de Travelpayouts (no necesitan token) y los guarda
en data/cache por 30 días.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .models import Tarifa
from .util import CACHE, aviso, horas_desde, leer_json, guardar_json, millas, sesion_http, ahora_iso

SJU = (18.4394, -66.0018)

URLS = {
    "cities": "https://api.travelpayouts.com/data/en/cities.json",
    "countries": "https://api.travelpayouts.com/data/en/countries.json",
    "airlines": "https://api.travelpayouts.com/data/en/airlines.json",
    "airports": "https://api.travelpayouts.com/data/en/airports.json",
}

REGIONES = {
    "japon": "Japón",
    "hawaii": "Hawaii",
    "usa": "EE.UU.",
    "canada": "Canadá",
    "europa": "Europa",
    "caribe": "Caribe",
    "latinoamerica": "Latinoamérica",
    "asia": "Asia",
    "oceania": "Oceanía",
    "medio_oriente_africa": "Medio Oriente y África",
    "otros": "Otros",
}

_EUROPA = set("GB FR ES PT IT DE NL BE IE CH AT DK SE NO FI IS PL CZ HU GR HR RO BG RS SI SK LT LV EE LU MT CY AL BA ME MK MD UA TR GE AM AZ MC AD LI SM VA GI FO".split())
_CARIBE = set("DO JM BS BB TT AG AW CW BQ SX MF BL KN LC VC GD DM GP MQ VI VG AI KY TC HT CU MS".split())
_LATAM = set("MX GT BZ SV HN NI CR PA CO VE EC PE BO CL AR UY PY BR GY SR GF".split())
_ASIA = set("CN HK MO TW KR KP TH VN SG MY ID PH IN LK NP MV KH LA MM BD PK MN KZ UZ KG TJ TM BN BT TL".split())
_OCEANIA = set("AU NZ FJ PF NC PG WS TO VU GU MP PW FM MH KI CK".split())
_MO_AF = set(
    "AE QA SA IL JO OM BH KW LB IQ IR EG MA TN DZ LY ZA KE TZ ET NG GH SN CI CM UG RW MU SC MG NA BW ZW ZM MZ AO CV".split()
)

PAISES_ES = {
    "US": "EE.UU.", "CA": "Canadá", "JP": "Japón", "ES": "España", "GB": "Reino Unido", "FR": "Francia",
    "IT": "Italia", "PT": "Portugal", "DE": "Alemania", "NL": "Países Bajos", "IE": "Irlanda", "CH": "Suiza",
    "BE": "Bélgica", "AT": "Austria", "GR": "Grecia", "TR": "Turquía", "IS": "Islandia", "DK": "Dinamarca",
    "SE": "Suecia", "NO": "Noruega", "FI": "Finlandia", "PL": "Polonia", "CZ": "Chequia", "HU": "Hungría",
    "HR": "Croacia", "MX": "México", "CO": "Colombia", "DO": "Rep. Dominicana", "CR": "Costa Rica",
    "PA": "Panamá", "PE": "Perú", "CL": "Chile", "AR": "Argentina", "BR": "Brasil", "EC": "Ecuador",
    "KR": "Corea del Sur", "CN": "China", "TH": "Tailandia", "VN": "Vietnam", "SG": "Singapur",
    "PH": "Filipinas", "ID": "Indonesia", "IN": "India", "AU": "Australia", "NZ": "Nueva Zelanda",
    "AE": "Emiratos Árabes", "QA": "Catar", "MA": "Marruecos", "EG": "Egipto", "ZA": "Sudáfrica",
    "JM": "Jamaica", "BS": "Bahamas", "AW": "Aruba", "CW": "Curazao", "VI": "Islas Vírgenes (EE.UU.)",
    "PR": "Puerto Rico", "CU": "Cuba", "GT": "Guatemala", "SV": "El Salvador", "HN": "Honduras",
    "NI": "Nicaragua", "VE": "Venezuela", "BO": "Bolivia", "UY": "Uruguay", "PY": "Paraguay",
    "TW": "Taiwán", "HK": "Hong Kong", "MY": "Malasia", "IL": "Israel", "SX": "Sint Maarten",
    "BB": "Barbados", "TT": "Trinidad y Tobago", "LC": "Santa Lucía", "AG": "Antigua y Barbuda",
}


def region_de(pais: Optional[str], lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    if not pais:
        return "otros"
    if pais == "JP":
        return "japon"
    if pais == "US":
        if lat is not None and lon is not None and lat < 25 and lon < -150:
            return "hawaii"
        return "usa"
    if pais == "CA":
        return "canada"
    for conjunto, nombre in (
        (_EUROPA, "europa"), (_CARIBE, "caribe"), (_LATAM, "latinoamerica"),
        (_ASIA, "asia"), (_OCEANIA, "oceania"), (_MO_AF, "medio_oriente_africa"),
    ):
        if pais in conjunto:
            return nombre
    return "otros"


def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", texto.lower()).strip()


class Lugares:
    def __init__(self, config: dict):
        self.config = config
        self.ciudades: dict = {}     # code -> {name, es, country, lat, lon}
        self.aeropuertos: dict = {}  # code -> {city, country, lat, lon}
        self.paises: dict = {}       # code -> name (en)
        self.paises_es: dict = {}    # code -> nombre (es), si viene en los datos
        self.paises_por_nombre: dict = {}
        self.aerolineas: dict = {}   # code -> name
        self.por_nombre: dict = {}   # nombre normalizado -> city code
        self.favoritos = {f["ciudad"]: f for f in config.get("favoritos", [])}
        self.fav_por_aeropuerto = {f.get("aeropuerto"): f for f in config.get("favoritos", []) if f.get("aeropuerto")}

    # -------------------------------------------------------------- carga
    def cargar(self) -> "Lugares":
        datos = {k: self._descargar(k, u) for k, u in URLS.items()}
        for c in datos["cities"] or []:
            coords = c.get("coordinates") or {}
            trad = c.get("name_translations") or {}
            self.ciudades[c["code"]] = {
                "name": c.get("name") or trad.get("en") or c["code"],
                "es": trad.get("es"),
                "country": c.get("country_code"),
                "lat": coords.get("lat"),
                "lon": coords.get("lon"),
                "vuela": c.get("has_flightable_airport", True) is not False,
            }
            for n in {c.get("name"), trad.get("en"), trad.get("es")}:
                if n:
                    self.por_nombre.setdefault(_normal(n), c["code"])
        for a in datos["airports"] or []:
            coords = a.get("coordinates") or {}
            self.aeropuertos[a["code"]] = {
                "city": a.get("city_code"), "country": a.get("country_code"),
                "lat": coords.get("lat"), "lon": coords.get("lon"),
            }
        for p in datos["countries"] or []:
            self.paises[p["code"]] = p.get("name") or p["code"]
            self.paises_por_nombre[_normal(p.get("name") or "")] = p["code"]
            es = (p.get("name_translations") or {}).get("es")
            if es:
                self.paises_es[p["code"]] = es
                self.paises_por_nombre.setdefault(_normal(es), p["code"])
        for al in datos["airlines"] or []:
            if al.get("code"):
                self.aerolineas[al["code"]] = al.get("name") or (al.get("name_translations") or {}).get("en") or al["code"]
        for f in self.favoritos.values():
            self.por_nombre[_normal(f["nombre"])] = f["ciudad"]
        return self

    def _descargar(self, clave: str, url: str):
        ruta = CACHE / f"{clave}.json"
        meta = leer_json(CACHE / "meta.json", {})
        if ruta.exists() and horas_desde(meta.get(clave)) < 24 * 30:
            return leer_json(ruta, [])
        try:
            r = sesion_http().get(url, timeout=60)
            r.raise_for_status()
            datos = r.json()
            guardar_json(ruta, datos, compacto=True)
            meta[clave] = ahora_iso()
            guardar_json(CACHE / "meta.json", meta)
            return datos
        except Exception as e:  # noqa: BLE001
            aviso(f"No pude bajar la lista de {clave} ({e}). Sigo con lo que haya en cache.")
            return leer_json(ruta, [])

    # -------------------------------------------------------------- búsquedas
    def nombre_aerolinea(self, codigo: Optional[str]) -> Optional[str]:
        if not codigo:
            return None
        return self.aerolineas.get(codigo, codigo)

    def buscar_por_texto(self, texto: str) -> Optional[str]:
        """'Madrid, Spain' -> 'MAD'. Devuelve código de ciudad o None."""
        if not texto:
            return None
        partes = [p.strip() for p in re.split(r",|\(|\)", texto) if p.strip()]
        for candidato in [texto] + partes:
            codigo = self.por_nombre.get(_normal(candidato))
            if codigo:
                return codigo
        m = re.search(r"\b([A-Z]{3})\b", texto)
        if m and (m.group(1) in self.ciudades or m.group(1) in self.aeropuertos):
            return m.group(1)
        return None

    def pais_por_texto(self, texto: str) -> Optional[str]:
        partes = [p.strip() for p in texto.split(",") if p.strip()]
        for p in reversed(partes):
            codigo = self.paises_por_nombre.get(_normal(p))
            if codigo:
                return codigo
        if re.search(r"hawaii", texto, re.I):
            return "US"
        return None

    # -------------------------------------------------------------- enriquecer
    def enriquecer(self, t: Tarifa) -> Tarifa:
        codigo = t.destino
        info = self.ciudades.get(codigo)
        if info is None and codigo in self.aeropuertos:
            ap = self.aeropuertos[codigo]
            if ap.get("city") in self.ciudades:
                codigo = ap["city"]
                info = self.ciudades[codigo]
            else:
                info = {"name": codigo, "es": None, "country": ap.get("country"), "lat": ap.get("lat"), "lon": ap.get("lon")}
        # Favoritos: por código de ciudad o de aeropuerto
        fav = self.favoritos.get(codigo) or self.favoritos.get(t.destino) or self.fav_por_aeropuerto.get(t.destino)
        if fav:
            t.destino = fav["ciudad"]
            info = self.ciudades.get(fav["ciudad"], info)
            t.favorito = True
            t.destino_nombre = fav["nombre"]
            t.region = fav.get("region")
            t.aeropuerto = fav.get("aeropuerto")
        else:
            t.destino = codigo
        if info:
            t.destino_nombre = t.destino_nombre or info.get("es") or info.get("name")
            t.pais = t.pais or info.get("country")
            if info.get("lat") is not None and info.get("lon") is not None:
                t.distancia = round(millas(SJU[0], SJU[1], info["lat"], info["lon"]))
            t.region = t.region or region_de(t.pais, info.get("lat"), info.get("lon"))
        if not t.destino_nombre:
            t.destino_nombre = t.destino_texto or t.destino
        if t.pais:
            t.pais_nombre = self.nombre_pais(t.pais)
        if t.region == "hawaii":
            t.pais_nombre = "Hawaii, EE.UU."
        if t.region is None:
            t.region = region_de(t.pais)
        if not t.aeropuerto and t.destino in self.aeropuertos:
            t.aeropuerto = t.destino
        if t.aerolinea and len(t.aerolinea) <= 3:
            t.aerolinea = self.nombre_aerolinea(t.aerolinea)
        return t


    # -------------------------------------------------------------- buscador de la página
    def nombre_pais(self, codigo: Optional[str]) -> Optional[str]:
        if not codigo:
            return None
        return PAISES_ES.get(codigo) or self.paises_es.get(codigo) or self.paises.get(codigo) or codigo

    def indice_buscador(self) -> list:
        """Lista compacta para el buscador de destinos de la página.
        Cada fila: [codigo, nombre_es, nombre_en, pais, tipo]  (tipo: c=ciudad, p=país, r=región)."""
        filas = []
        for codigo, nombre in REGIONES.items():
            if codigo != "otros":
                filas.append([codigo, nombre, "", "", "r"])
        filas.append(["*", "Cualquier error de tarifa (a donde sea)", "", "", "r"])
        for codigo in sorted(self.paises):
            if codigo == "PR":
                continue
            filas.append([codigo, self.nombre_pais(codigo), self.paises.get(codigo, ""), "", "p"])
        for codigo, c in self.ciudades.items():
            if not c.get("vuela", True) or c.get("country") == "PR":
                continue
            fav = self.favoritos.get(codigo)
            nombre_es = (fav or {}).get("nombre") or c.get("es") or c.get("name") or codigo
            en = c.get("name") or ""
            filas.append([codigo, nombre_es, "" if en == nombre_es else en, c.get("country") or "", "c"])
        return filas
