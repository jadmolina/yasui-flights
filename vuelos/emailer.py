"""Emails de Yasui Flights por Gmail (con App Password).

Cada persona recibe su propio email: solo ve su correo en el "Para".
"""
from __future__ import annotations

import html
import re
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from typing import Dict, List, Optional

from .lugares import REGIONES

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
# Paleta de Yasui Flights (verde bosque, khaki y marrón)
NARANJA, VERDE_AGUA, AZUL, TINTA, GRIS, LINEA = "#8A6240", "#4C6444", "#4D2D18", "#102820", "#5F6A5E", "#E0D5C1"
FONDO, PANEL, KHAKI, KHAKI_SUAVE, AVISO = "#F3EDE2", "#FBF8F2", "#CABA9C", "#EAE1D0", "#8A4B1F"
e = html.escape


def _f(d: Optional[str]) -> str:
    if not d:
        return ""
    try:
        x = date.fromisoformat(d[:10])
    except ValueError:
        return d
    return f"{x.day} {MESES[x.month - 1]}"


def _dinero(n) -> str:
    return "—" if n is None else f"${n:,.0f}"


def _fechas(salida: Optional[str], regreso: Optional[str]) -> str:
    if salida and regreso:
        return f"{_f(salida)} → {_f(regreso)}"
    if salida:
        return f"{_f(salida)} (solo ida)"
    return "fechas en el post"


def _lista_bonita(nombres: List[str]) -> str:
    nombres = [n for n in nombres if n]
    if len(nombres) <= 1:
        return "".join(nombres)
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def nombres_destinos(destinos: List[dict]) -> List[str]:
    return [d.get("n") or REGIONES.get(d.get("c"), d.get("c")) for d in destinos or []]


def destinatarios(para: str, usuario: str) -> List[str]:
    """'a@x.com, b@y.com; c@z.com' -> lista sin repetidos. Vacío = le llega al mismo Gmail que manda."""
    lista: List[str] = []
    for d in re.split(r"[,;\s]+", para or ""):
        d = d.strip()
        if d and "@" in d and d.lower() not in (x.lower() for x in lista):
            lista.append(d)
    return lista or ([usuario] if usuario else [])


# ======================================================================= asuntos
def asunto(ofertas: List[dict]) -> str:
    p = ofertas[0]
    tipo = "ida y vuelta" if p["ida_y_vuelta"] else "solo ida"
    combo = " (combinado)" if p.get("tipo") == "combinado" else ""
    if p["nivel"] == 3:
        base = f"Posible error de tarifa: {p['destino_nombre']} {_dinero(p['precio'])} {tipo}{combo}"
    else:
        base = f"Vuelo barato: {p['destino_nombre']} {_dinero(p['precio'])} {tipo}{combo}"
    if len(ofertas) > 1:
        base += f" (+{len(ofertas) - 1} más)"
    return base


# ======================================================================= piezas
def _boton(texto: str, url: str, primario: bool = True) -> str:
    if primario:
        estilo = f"background:{TINTA};color:#fff;border:1px solid {TINTA}"
    else:
        estilo = f"background:{PANEL};color:{TINTA};border:1px solid {KHAKI}"
    return (f"<a href='{e(url)}' style='display:inline-block;{estilo};text-decoration:none;padding:8px 12px;"
            f"border-radius:8px;font-size:13px;font-weight:600;margin:8px 6px 0 0'>{e(texto)}</a>")


def _color(o: dict) -> str:
    return NARANJA if o["nivel"] == 3 else (VERDE_AGUA if o["nivel"] == 2 else AZUL)


def _titulo_destino(o: dict) -> str:
    extra = f", {e(o['pais_nombre'])}" if o.get("pais_nombre") and o.get("pais_nombre") != o.get("destino_nombre") else ""
    return f"<div style='font-size:18px;font-weight:700;color:{TINTA};margin-top:2px'>{e(o['destino_nombre'])}{extra}</div>"


def _fila_directa(o: dict) -> str:
    color = _color(o)
    normal = ""
    if o.get("mediana"):
        normal = f"Normal ~{_dinero(o['mediana'])}"
        if o.get("descuento") and o["descuento"] > 0:
            normal += f" · <b style='color:#4C6444'>{o['descuento']:.0%} menos</b>"
    elif o.get("meta"):
        normal = f"Precio meta: {_dinero(o.get('meta'))}"
    escalas = None if o.get("escalas") is None else ("directo" if o["escalas"] == 0 else f"{o['escalas']} escala(s)")
    vuelo = " · ".join(x for x in [o.get("aerolinea"), escalas] if x)
    verif = ""
    if o.get("verificado") is True and o.get("fuente") != "google":
        verif = f"<div style='font-size:12px;color:#4C6444;margin-top:4px'>Confirmado en Google Flights: {_dinero(o.get('precio_google'))}</div>"
    botones = _boton("Google Flights", o["link_google"])
    if o.get("link") and o.get("fuente") != "google":
        botones += _boton("Ver post" if o["fuente"] == "feed" else "Aviasales", o["link"], primario=False)
    return f"""
<tr><td style="padding:14px 16px;border-bottom:1px solid {LINEA}">
  <div style="font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:{color}">{e(o['nivel_nombre'])} · {e(REGIONES.get(o.get('region') or '', ''))}</div>
  {_titulo_destino(o)}
  <div style="margin-top:4px"><span style="font-size:28px;font-weight:800;color:{color}">{_dinero(o['precio'])}</span>
     <span style="font-size:13px;color:{GRIS}"> {'ida y vuelta' if o['ida_y_vuelta'] else 'solo ida'} desde SJU</span></div>
  <div style="font-size:13px;color:{GRIS}">{normal}</div>
  <div style="font-size:13px;color:{TINTA};margin-top:4px">{e(_fechas(o.get('salida'), o.get('regreso')))}{(' · ' + e(vuelo)) if vuelo else ''}</div>
  {f"<div style='font-size:12px;color:{GRIS};font-style:italic;margin-top:4px'>{e(o['titulo'])}</div>" if o.get('titulo') else ''}
  {verif}
  <div style="font-size:12px;color:{GRIS};margin-top:4px">{e(' · '.join(o.get('motivos') or []))}</div>
  {botones}
</td></tr>"""


def _fila_combinado(o: dict) -> str:
    color = _color(o)
    p, t = o["puente"], o["tramo"]
    ciudad, dest = p["nombre"], o["destino_nombre"]
    aprox = "" if p.get("exacto") else " aprox."
    ahorro = ""
    if o.get("directo"):
        ahorro = f"Normal desde SJU ~{_dinero(o['directo'])}"
        if o.get("descuento") and o["descuento"] > 0:
            ahorro += f" · <b style='color:#4C6444'>{o['descuento']:.0%} menos</b>"

    alguna_fecha = bool(p.get("salida") or t.get("salida"))

    def fila(fecha, desde, hasta):
        celda_fecha = (f"<td style='padding:2px 10px 2px 0;font-size:13px;color:{GRIS};white-space:nowrap;width:60px'>"
                       f"{e(_f(fecha)) if fecha else '—'}</td>") if alguna_fecha else ""
        return f"<tr>{celda_fecha}<td style='padding:2px 0;font-size:14px;color:{TINTA}'>{e(desde)} → {e(hasta)}</td></tr>"

    def titulo_seccion(txt):
        return (f"<tr><td colspan='2' style='padding:6px 0 2px;font-size:11px;font-weight:700;letter-spacing:.07em;"
                f"text-transform:uppercase;color:{GRIS}'>{txt}</td></tr>")

    itinerario = (titulo_seccion("Ida") + fila(p.get("salida"), "SJU", ciudad) + fila(t.get("salida"), ciudad, dest)
                  + titulo_seccion("Vuelta") + fila(t.get("regreso"), dest, ciudad) + fila(p.get("regreso"), ciudad, "SJU"))
    nota = ""
    if not (p.get("salida") and t.get("salida")):
        nota = (f"<div style='font-size:12px;color:{GRIS};margin-top:4px'>"
                f"{'' if t.get('salida') else 'Las fechas del vuelo a ' + e(dest) + ' están en el post. '}"
                f"El precio SJU ⇄ {e(ciudad)} es el típico; depende de las fechas que escojas.</div>")
    cambio = (f"Llegas a {p['aeropuerto']} y el vuelo a {dest} sale de {t['aeropuerto_origen']} (otro aeropuerto). "
              if p.get("aeropuerto") and t.get("aeropuerto_origen") and p["aeropuerto"] != t["aeropuerto_origen"] else "")
    bol = "font-size:13px;color:%s;padding:3px 0;border-bottom:1px dashed %s" % (TINTA, LINEA)
    aer_t = " · ".join(x for x in [t.get("aerolinea"), t.get("sitio")] if x)
    return f"""
<tr><td style="padding:14px 16px;border-bottom:1px solid {LINEA}">
  <div style="font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:{color}">Combinado · {e(o['nivel_nombre'])} · {e(REGIONES.get(o.get('region') or '', ''))}</div>
  {_titulo_destino(o)}
  <div style="margin-top:4px"><span style="font-size:28px;font-weight:800;color:{color}">{_dinero(o['precio'])}</span>
     <span style="font-size:13px;color:{GRIS}"> total{aprox} ida y vuelta</span></div>
  <div style="font-size:13px;color:{GRIS}">{ahorro}</div>
  <div style="background:{KHAKI_SUAVE};border-radius:10px;padding:6px 10px 8px;margin-top:6px">
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">{itinerario}</table>{nota}
  </div>
  <div style="font-size:12px;color:{GRIS};margin-top:8px">Son 2 boletos separados:</div>
  <div style="{bol}">SJU ⇄ {e(ciudad)}: <b>{'' if p.get('exacto') else '~'}{_dinero(p['precio'])}</b>{(' · ' + e(p['aerolinea'])) if p.get('aerolinea') else ''}</div>
  <div style="{bol}">{e(ciudad)} ⇄ {e(dest)}: <b>{_dinero(t['precio'])}</b>{(' · ' + e(aer_t)) if aer_t else ''}</div>
  {f"<div style='font-size:12px;color:{GRIS};font-style:italic;margin-top:4px'>{e(t['titulo'])}</div>" if t.get('titulo') else ''}
  <div style="font-size:12px;color:{AVISO};margin-top:6px">{e(cambio)}Si un vuelo se atrasa, la otra aerolínea no te espera: por eso llegas un día antes.</div>
  <div style="font-size:12px;color:{GRIS};margin-top:4px">{e(' · '.join(o.get('motivos') or []))}</div>
  {_boton('Boleto SJU ⇄ ' + ciudad, p['link'])}{_boton('Boleto ' + ciudad + ' ⇄ ' + dest, t['link'], primario=False)}
</td></tr>"""


def _fila(o: dict) -> str:
    return _fila_combinado(o) if o.get("tipo") == "combinado" else _fila_directa(o)


def _plantilla(titulo: str, intro_html: str, filas_html: str, pie_html: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:{FONDO};font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{FONDO}"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:{PANEL};border-radius:16px;overflow:hidden;border:1px solid {LINEA}">
<tr><td style="background:{TINTA};color:#EDE3CF;padding:20px 16px">
  <div style="font:600 12px monospace;letter-spacing:.12em;color:{KHAKI}">YASUI FLIGHTS · SJU → A DONDE SEA</div>
  <div style="font-size:22px;font-weight:700;margin-top:6px;font-family:Georgia,'Times New Roman',serif">{e(titulo)}</div>
</td></tr>
{intro_html}
{filas_html}
<tr><td style="padding:14px 16px;font-size:12px;color:{GRIS}">
  Los errores de tarifa duran poco: reserva rápido y no pagues hotel hasta que la aerolínea confirme.
  Desde Puerto Rico aplica la regla de 24 horas del DOT (cancelación gratis si reservas con 7+ días de anticipación).
  {pie_html}
</td></tr>
</table></td></tr></table></body></html>"""


def _pie(persona: Optional[dict], url_sitio: str) -> str:
    partes = []
    if persona and persona.get("destinos"):
        partes.append(f"Recibes esto porque escogiste: <b>{e(_lista_bonita(nombres_destinos(persona['destinos'])))}</b>.")
    enlaces = []
    if url_sitio:
        enlaces.append(f"<a href='{e(url_sitio)}' style='color:{NARANJA};font-weight:600'>Ver ofertas o cambiar mis destinos</a>")
        if persona and persona.get("token_baja"):
            enlaces.append(f"<a href='{e(link_baja(url_sitio, persona['token_baja']))}' style='color:{GRIS}'>Darme de baja</a>")
    if enlaces:
        partes.append(" · ".join(enlaces))
    return "".join(f"<p style='margin:12px 0 0'>{p}</p>" for p in partes)


def link_baja(url_sitio: str, token: str) -> str:
    return f"{url_sitio.rstrip('/')}/#baja={token}"


def _hola(persona: Optional[dict]) -> str:
    nombre = (persona or {}).get("nombre")
    return f"¡Hola, {nombre}!" if nombre else "¡Hola!"


# ======================================================================= emails completos
def email_ofertas(ofertas: List[dict], persona: Optional[dict] = None, url_sitio: str = "") -> Dict[str, str]:
    n = len(ofertas)
    titulo = f"{n} oferta{'s' if n != 1 else ''} nueva{'s' if n != 1 else ''} para ti"
    intro = (f"<tr><td style='padding:14px 16px 4px;font-size:14px;color:{TINTA}'>{e(_hola(persona))} "
             f"Salió algo bueno para los lugares que escogiste:</td></tr>") if persona and persona.get("destinos") else ""
    return {
        "asunto": asunto(ofertas),
        "html": _plantilla(titulo, intro, "".join(_fila(o) for o in ofertas[:15]), _pie(persona, url_sitio)),
        "texto": cuerpo_texto(ofertas, url_sitio, persona),
    }


def email_bienvenida(persona: dict, ofertas: List[dict], precios: List[dict], url_sitio: str = "") -> Dict[str, str]:
    lugares = _lista_bonita(nombres_destinos(persona.get("destinos")))
    intro = (f"<tr><td style='padding:16px 16px 6px;font-size:14px;color:{TINTA};line-height:1.5'>"
             f"{e(_hola(persona))} Ya te apuntaste en Yasui Flights. Buscamos vuelos cada 4 horas y te escribimos "
             f"solo cuando sale algo bueno para: <b>{e(lugares)}</b>.</td></tr>")
    filas = ""
    if precios:
        celdas = "".join(
            f"<tr><td style='padding:6px 0;font-size:13px;color:{TINTA}'>{e(p['nombre'])}</td>"
            f"<td style='padding:6px 0;font-size:13px;text-align:right;font-weight:700;color:{TINTA}'>{_dinero(p['precio'])}</td>"
            f"<td style='padding:6px 0 6px 10px;font-size:12px;color:{GRIS};text-align:right'>{e(_fechas(p.get('salida'), p.get('regreso')) if p.get('salida') else '')}</td></tr>"
            for p in precios[:12])
        filas += (f"<tr><td style='padding:6px 16px 10px'><div style='font-size:12px;font-weight:700;letter-spacing:.05em;"
                  f"text-transform:uppercase;color:{GRIS};margin-bottom:4px'>Precios de hoy desde SJU (ida y vuelta)</div>"
                  f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>{celdas}</table></td></tr>")
    if ofertas:
        filas += (f"<tr><td style='padding:8px 16px 0;font-size:12px;font-weight:700;letter-spacing:.05em;"
                  f"text-transform:uppercase;color:{NARANJA}'>Ofertas que hay ahora mismo</td></tr>")
        filas += "".join(_fila(o) for o in ofertas[:10])
    else:
        filas += (f"<tr><td style='padding:6px 16px 12px;font-size:13px;color:{GRIS}'>Ahora mismo no hay nada loco para tus destinos. "
                  f"Apenas salga algo, te llega un email.</td></tr>")
    texto = f"{_hola(persona)} Ya te apuntaste en Yasui Flights. Te escribimos cuando salga algo bueno para: {lugares}.\n\n"
    texto += cuerpo_texto(ofertas, url_sitio, persona) if ofertas else (f"Ver la página: {url_sitio}\n" if url_sitio else "")
    return {
        "asunto": "¡Listo! Ya estás en Yasui Flights",
        "html": _plantilla("¡Bienvenido a Yasui Flights!", intro, filas, _pie(persona, url_sitio)),
        "texto": texto,
    }


def cuerpo_html(ofertas: List[dict], url_sitio: str = "", persona: Optional[dict] = None) -> str:
    return email_ofertas(ofertas, persona, url_sitio)["html"]


def cuerpo_texto(ofertas: List[dict], url_sitio: str = "", persona: Optional[dict] = None) -> str:
    lineas = []
    for o in ofertas[:15]:
        tipo = "ida y vuelta" if o["ida_y_vuelta"] else "solo ida"
        if o.get("tipo") == "combinado":
            p, t = o["puente"], o["tramo"]
            c, d = p["nombre"], o["destino_nombre"]
            lineas.append(f"[Combinado · {o['nivel_nombre']}] {d}: {_dinero(o['precio'])} total {tipo}")
            lineas.append(f"   Ida:    {_f(p.get('salida')) or '—'} SJU -> {c} | {_f(t.get('salida')) or '—'} {c} -> {d}")
            lineas.append(f"   Vuelta: {_f(t.get('regreso')) or '—'} {d} -> {c} | {_f(p.get('regreso')) or '—'} {c} -> SJU")
            lineas.append(f"   Boleto SJU <-> {c}: {'~' if not p.get('exacto') else ''}{_dinero(p['precio'])}  {p['link']}")
            lineas.append(f"   Boleto {c} <-> {d}: {_dinero(t['precio'])}  {t['link']}")
        else:
            lineas.append(f"[{o['nivel_nombre']}] {o['destino_nombre']}: {_dinero(o['precio'])} {tipo} "
                          f"{_fechas(o.get('salida'), o.get('regreso'))}")
            lineas.append(f"   {o['link_google']}")
    if url_sitio:
        lineas += ["", f"Ver ofertas o cambiar mis destinos: {url_sitio}"]
        if persona and persona.get("token_baja"):
            lineas.append(f"Darme de baja: {link_baja(url_sitio, persona['token_baja'])}")
    return "\n".join(lineas)


# ======================================================================= envío
class Cartero:
    """Una sola conexión a Gmail para mandar muchos emails, uno por persona."""

    def __init__(self, usuario: str, clave: str, remitente: str = "Yasui Flights"):
        self.usuario, self.clave, self.remitente = usuario, clave.replace(" ", ""), remitente
        self.smtp = None
        self.enviados = 0

    def __enter__(self) -> "Cartero":
        self.smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30)
        self.smtp.__enter__()
        self.smtp.login(self.usuario, self.clave)
        return self

    def __exit__(self, *exc) -> None:
        if self.smtp is not None:
            self.smtp.__exit__(*exc)

    def mandar(self, para: str, contenido: Dict[str, str], baja: Optional[str] = None) -> None:
        msg = EmailMessage()
        msg["Subject"] = contenido["asunto"]
        msg["From"] = f"{self.remitente} <{self.usuario}>"
        msg["To"] = para
        if baja:
            msg["List-Unsubscribe"] = f"<{baja}>"
        msg.set_content(contenido["texto"])
        msg.add_alternative(contenido["html"], subtype="html")
        self.smtp.send_message(msg, from_addr=self.usuario, to_addrs=[para])
        self.enviados += 1


def enviar(ofertas: List[dict], usuario: str, clave: str, para: str, url_sitio: str = "",
           remitente: str = "Yasui Flights") -> int:
    """Manda las mismas ofertas a una lista de emails, un email aparte para cada uno."""
    if not ofertas:
        return 0
    lista = destinatarios(para, usuario)
    with Cartero(usuario, clave, remitente) as c:
        for persona in lista:
            c.mandar(persona, email_ofertas(ofertas, None, url_sitio))
    return len(lista)
