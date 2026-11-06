#!/usr/bin/env python3
"""Yasui Flights: busca vuelos baratos desde Puerto Rico y le avisa a cada persona
solo de los destinos que escogió.

Uso:
  python run.py                 Busca, actualiza la página y manda los emails
  python run.py --sin-email     Igual, pero sin mandar emails
  python run.py --demo          Página de ejemplo (docs/demo.html) sin claves ni internet
  python run.py --probar-email  Manda un email de ejemplo a EMAIL_TO (o al mismo Gmail)
  python run.py --solo feeds    Usa una sola fuente: travelpayouts | google | feeds
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from typing import Dict, List

from vuelos import emailer, site, suscriptores
from vuelos.combinados import Combinador
from vuelos.detector import Detector, coincide
from vuelos.lugares import Lugares
from vuelos.util import DATA, DOCS, ahora_iso, aviso, cargar_config, cargar_env, env, guardar_json, log

MAX_EMAILS_POR_CORRIDA = 400  # Gmail deja ~500 al día


# ---------------------------------------------------------------------------- ayudantes
def intereses_de(personas: List[dict], config: dict) -> List[dict]:
    """Todo lo que alguien quiere (destinos de la gente + destinos base)."""
    todo = [d for p in personas for d in (p.get("destinos") or [])]
    todo += [{"t": "c", "c": f["ciudad"], "n": f["nombre"]} for f in config.get("favoritos", [])]
    return todo


def ciudades_de(personas: List[dict]) -> List[str]:
    """Ciudades que escogió la gente, las más pedidas primero."""
    cuenta = Counter(d["c"] for p in personas for d in (p.get("destinos") or []) if d.get("t") == "c" and d.get("c"))
    return [c for c, _ in cuenta.most_common()]


def precios_para(persona: dict, precios: Dict[str, dict]) -> List[dict]:
    filas = []
    for d in persona.get("destinos") or []:
        if d.get("t") == "c" and d.get("c") in precios:
            p = dict(precios[d["c"]])
            p["nombre"] = d.get("n") or p.get("nombre") or d["c"]
            filas.append(p)
    return filas


def armar_emails(det: Detector, personas: List[dict], avisos: Dict[str, dict], ofertas: List[dict],
                 precios: Dict[str, dict], url_sitio: str) -> List[tuple]:
    """Devuelve [(persona, contenido, ofertas_incluidas, es_bienvenida)]."""
    salida = []
    for p in personas:
        av = avisos.get(p["id"], {})
        if not p.get("bienvenida"):
            actuales = det.por_avisar(ofertas, p.get("destinos"), av, solo_nuevas=False)
            salida.append((p, emailer.email_bienvenida(p, actuales, precios_para(p, precios), url_sitio), actuales, True))
        else:
            nuevas = det.por_avisar(ofertas, p.get("destinos"), av)
            if nuevas:
                salida.append((p, emailer.email_ofertas(nuevas, p, url_sitio), nuevas, False))
    return salida


def mandar_emails(det: Detector, store, pendientes: List[tuple], avisos: Dict[str, dict], config: dict, url_sitio: str) -> int:
    usuario, clave = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
    if not (usuario and clave):
        aviso(f"Hay {len(pendientes)} email(s) para mandar pero faltan GMAIL_USER / GMAIL_APP_PASSWORD.")
        return 0
    remitente = config.get("email", {}).get("nombre_remitente", "Yasui Flights")
    enviados = 0
    with emailer.Cartero(usuario, clave, remitente) as cartero:
        for persona, contenido, incluidas, bienvenida in pendientes[:MAX_EMAILS_POR_CORRIDA]:
            baja = emailer.link_baja(url_sitio, persona["token_baja"]) if url_sitio and persona.get("token_baja") else None
            try:
                cartero.mandar(persona["email"], contenido, baja)
            except Exception as e:  # noqa: BLE001
                aviso(f"No pude mandarle el email a una persona: {e}")
                continue
            enviados += 1
            av = det.marcar_avisados(incluidas, avisos.setdefault(persona["id"], {}))
            avisos[persona["id"]] = av
            store.guardar_avisos(persona["id"], av, [det.clave_aviso(o) for o in incluidas])
            if bienvenida:
                store.marcar_bienvenida(persona["id"])
    return enviados


# ---------------------------------------------------------------------------- demo
def correr_demo(config: dict, mandar: bool) -> int:
    from vuelos import demo

    lugares = demo.lugares_demo(config)
    carpeta = DATA / "demo"
    carpeta.mkdir(parents=True, exist_ok=True)
    for f in ("ofertas.json", "avisados.json"):
        (carpeta / f).unlink(missing_ok=True)
    det = Detector(config, lugares, carpeta=carpeta)
    det.historial = demo.historial_demo()
    tarifas = det.preparar(demo.tarifas_demo())
    det.actualizar_historial(tarifas)
    personas = demo.personas_demo()
    intereses = intereses_de(personas, config)
    combos = Combinador(config, det, lugares, tp=demo.TravelpayoutsDemo()).construir(
        tarifas, lambda t: coincide({"destino": t.destino, "aeropuerto": t.aeropuerto, "pais": t.pais,
                                     "region": t.region, "nivel": 3 if t.es_error else 0}, intereses))
    ofertas = det.combinar(det.evaluar_todas(tarifas) + combos)
    for o in ofertas:  # simula la verificación con Google
        if o["destino"] == "TYO" and o.get("tipo") != "combinado":
            o.update(verificado=True, precio_google=412)
        if o["destino"] == "PAR" and o.get("tipo") != "combinado":
            o.update(verificado=False, precio_google=690)
    precios = det.precios_mapa(tarifas)
    datos = site.armar_datos(config, ahora_iso(), det.hoy, ofertas, precios, lugares.indice_buscador(), [], demo=True)
    datos["config"]["supabase_url"] = ""  # la demo siempre usa el login de prueba (código 123456)
    ruta = site.generar(datos, "demo.html")
    log(f"Página demo: {ruta}")
    n_combo = sum(o.get("tipo") == "combinado" for o in ofertas)
    log(f"Ofertas demo: {len(ofertas)} ({sum(o['nivel'] == 3 for o in ofertas)} posibles errores, {n_combo} combinados)")
    url = env("SITE_URL") or "https://ejemplo.github.io/yasui-flights/"
    pendientes = armar_emails(det, personas, {}, ofertas, precios, url)
    for i, (persona, contenido, incluidas, bienvenida) in enumerate(pendientes):
        nombre = f"demo-email-{i + 1}.html"
        (DOCS / nombre).write_text(contenido["html"], encoding="utf-8")
        log(f"Email demo para {persona['nombre'] or persona['email']}: {DOCS / nombre}  ->  {contenido['asunto']} ({len(incluidas)} ofertas)")
    if mandar:
        usuario, clave = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
        if not (usuario and clave):
            aviso("Faltan GMAIL_USER y GMAIL_APP_PASSWORD en el .env")
            return 1
        prueba = det.por_avisar(ofertas, None, {})
        n = emailer.enviar(prueba, usuario, clave, env("EMAIL_TO"), env("SITE_URL"),
                           config.get("email", {}).get("nombre_remitente", "Yasui Flights"))
        log(f"Email de prueba enviado a {n} persona(s), cada una por separado")
    return 0


# ---------------------------------------------------------------------------- principal
def main() -> int:
    p = argparse.ArgumentParser(description="Yasui Flights: vuelos baratos desde Puerto Rico")
    p.add_argument("--sin-email", action="store_true", help="no manda emails")
    p.add_argument("--demo", action="store_true", help="página de ejemplo, sin internet")
    p.add_argument("--probar-email", action="store_true", help="manda un email de prueba")
    p.add_argument("--solo", choices=["travelpayouts", "google", "feeds"], help="usar una sola fuente")
    args = p.parse_args()

    cargar_env()
    config = cargar_config()
    origen = config.get("origen", "SJU")
    if args.demo or args.probar_email:
        return correr_demo(config, mandar=args.probar_email)

    inicio = time.time()
    log(f"Buscando vuelos baratos desde {origen}...")
    lugares = Lugares(config).cargar()
    det = Detector(config, lugares)
    url_sitio = env("SITE_URL")

    # ---------------- ¿Quién recibe ofertas?
    store = suscriptores.conectar()
    try:
        personas = store.suscriptores()
    except Exception as e:  # noqa: BLE001
        aviso(f"No pude leer la gente apuntada ({e}). Sigo sin mandar emails personalizados.")
        personas = []
    log(f"  {len(personas)} persona(s) recibiendo ofertas ({store.modo})")
    intereses = intereses_de(personas, config)
    ciudades = ciudades_de(personas)
    det.elegidos = set(ciudades)
    usar = (lambda f: args.solo in (None, f))
    tarifas, fuentes = [], []

    # ---------------- Travelpayouts (SJU + ciudades puente)
    tp = None
    token = env("TRAVELPAYOUTS_TOKEN")
    if usar("travelpayouts") and config.get("travelpayouts", {}).get("activo", True):
        if not token:
            aviso("No hay TRAVELPAYOUTS_TOKEN; me salto Aviasales.")
            fuentes.append({"nombre": "Aviasales", "ok": False, "activo": False, "detalle": "falta el token"})
        else:
            from vuelos.sources.travelpayouts import Travelpayouts
            try:
                tp = Travelpayouts(token, config)
                nuevas = tp.buscar(ciudades)
                if config.get("combinados", {}).get("activo", True):
                    nuevas += tp.buscar_puentes(config["combinados"].get("puentes", []))
                tarifas += nuevas
                fuentes.append({"nombre": "Aviasales", "ok": bool(nuevas) or not tp.errores, "n": len(nuevas),
                                "detalle": "; ".join(tp.errores[-2:])})
            except Exception as e:  # noqa: BLE001
                aviso(f"Travelpayouts falló: {e}")
                fuentes.append({"nombre": "Aviasales", "ok": False, "detalle": str(e)[:200]})
                tp = None

    # ---------------- Feeds
    if usar("feeds") and config.get("feeds", {}).get("activo", True):
        from vuelos.sources.feeds import Feeds
        fd = Feeds(config)
        try:
            tarifas += fd.buscar()
        except Exception as e:  # noqa: BLE001
            aviso(f"Feeds fallaron: {e}")
        for nombre, est in fd.estado.items():
            fuentes.append({"nombre": nombre, "ok": est.get("ok", False), "n": est.get("desde_pr"),
                            "detalle": est.get("error") or f"{est.get('posts', 0)} posts revisados"})

    # ---------------- Google Flights (escaneo)
    gf = None
    if usar("google") and config.get("google_flights", {}).get("activo", True):
        from vuelos.sources.google_flights import DISPONIBLE, ERROR_IMPORT, GoogleFlights
        if DISPONIBLE:
            gf = GoogleFlights(config)
            tarifas += gf.escanear(ciudades)
        else:
            aviso(f"Google Flights no disponible: {ERROR_IMPORT}")
            fuentes.append({"nombre": "Google Flights", "ok": False, "activo": False,
                            "detalle": f"no disponible: {ERROR_IMPORT}"[:200]})

    # ---------------- Evaluar
    tarifas = det.preparar(tarifas)
    det.actualizar_historial(tarifas)
    ofertas = det.evaluar_todas(tarifas)

    def quiere(t) -> bool:
        return coincide({"destino": t.destino, "aeropuerto": t.aeropuerto, "pais": t.pais, "region": t.region,
                         "nivel": 3 if t.es_error else 0}, intereses)

    try:
        ofertas += Combinador(config, det, lugares, tp).construir(tarifas, quiere)
    except Exception as e:  # noqa: BLE001
        aviso(f"Los combinados fallaron: {e}")
    ofertas = det.combinar(ofertas)
    if gf is not None:
        revisadas = gf.verificar(ofertas)
        if revisadas:
            antes = len(ofertas)
            ofertas = det.quitar_no_confirmadas(ofertas)
            log(f"  Google Flights verificó {revisadas} ofertas; {antes - len(ofertas)} ya no estaban a ese precio")
        fuentes.append({"nombre": "Google Flights", "ok": not gf.bloqueado, "n": gf.busquedas,
                        "detalle": "; ".join(gf.errores[-2:]) or f"{gf.busquedas} búsquedas"})
    precios = det.precios_mapa(tarifas)
    n3 = sum(o["nivel"] == 3 for o in ofertas)
    n_combo = sum(o.get("tipo") == "combinado" for o in ofertas)
    log(f"Resultado: {len(ofertas)} ofertas ({n3} posibles errores, {n_combo} combinados)")

    # ---------------- Emails, uno por persona
    if not args.sin_email and config.get("email", {}).get("activo", True) and personas:
        try:
            avisos = store.avisos()
        except Exception as e:  # noqa: BLE001
            aviso(f"No pude leer los avisos anteriores ({e}); no mando emails esta vez para no repetir.")
            avisos = None
        if avisos is not None:
            pendientes = armar_emails(det, personas, avisos, ofertas, precios, url_sitio)
            if pendientes:
                try:
                    n = mandar_emails(det, store, pendientes, avisos, config, url_sitio)
                    log(f"Emails enviados: {n} de {len(pendientes)}")
                except Exception as e:  # noqa: BLE001
                    aviso(f"No pude conectar con Gmail: {e}")
            else:
                log("No hay nada nuevo para nadie.")
    elif args.sin_email:
        log("(--sin-email: no mandé emails)")

    # ---------------- Guardar y página
    det.guardar(ofertas)
    datos = site.armar_datos(config, det.corrida, det.hoy, ofertas, precios, lugares.indice_buscador(), fuentes)
    ruta = site.generar(datos)
    guardar_json(DATA / "estado.json", {"ultima_corrida": det.corrida, "segundos": round(time.time() - inicio),
                                         "tarifas": len(tarifas), "ofertas": len(ofertas), "personas": len(personas),
                                         "fuentes": fuentes})
    log(f"Página: {ruta}  ({round(time.time() - inicio)} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
