"""Quién recibe ofertas y qué escogió.

- Con Supabase (SUPABASE_URL + SUPABASE_SECRET_KEY): la gente que se apuntó en la página.
- Sin Supabase (modo local): los emails de EMAIL_TO, y les llega todo.
"""
from __future__ import annotations

from typing import Dict, List

import requests

from .util import DATA, aviso, env, guardar_json, leer_json

UA = "yasui-flights-bot/1.0 (+python-requests)"  # Supabase rechaza la secret key si parece un navegador


class Supabase:
    modo = "supabase"

    def __init__(self, url: str, clave: str):
        self.url = url.rstrip("/")
        self.http = requests.Session()
        self.http.headers.update({"apikey": clave, "User-Agent": UA, "Content-Type": "application/json"})
        if clave.startswith("eyJ"):  # clave vieja (service_role JWT)
            self.http.headers["Authorization"] = f"Bearer {clave}"

    def _get(self, ruta: str, params: dict) -> list:
        r = self.http.get(f"{self.url}/rest/v1/{ruta}", params=params, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:200]}")
        return r.json()

    def suscriptores(self) -> List[dict]:
        filas = self._get("suscriptores", {
            "select": "user_id,email,nombre,destinos,activo,bienvenida_enviada,token_baja",
            "activo": "is.true",
        })
        return [{
            "id": f["user_id"], "email": f["email"], "nombre": (f.get("nombre") or "").strip(),
            "destinos": f.get("destinos") or [], "bienvenida": bool(f.get("bienvenida_enviada")),
            "token_baja": f.get("token_baja"),
        } for f in filas if f.get("email") and f.get("destinos")]

    def avisos(self) -> Dict[str, Dict[str, dict]]:
        res: Dict[str, Dict[str, dict]] = {}
        for f in self._get("avisos", {"select": "user_id,clave,precio,fecha"}):
            res.setdefault(f["user_id"], {})[f["clave"]] = {"precio": float(f["precio"]), "fecha": f["fecha"]}
        return res

    def guardar_avisos(self, user_id: str, avisos: Dict[str, dict], claves: List[str]) -> None:
        filas = [{"user_id": user_id, "clave": k, "precio": avisos[k]["precio"], "fecha": avisos[k]["fecha"]}
                 for k in claves if k in avisos]
        if not filas:
            return
        r = self.http.post(f"{self.url}/rest/v1/avisos", params={"on_conflict": "user_id,clave"}, json=filas,
                           headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, timeout=30)
        if r.status_code >= 400:
            aviso(f"No pude guardar los avisos en Supabase: {r.status_code} {r.text[:160]}")

    def marcar_bienvenida(self, user_id: str) -> None:
        r = self.http.patch(f"{self.url}/rest/v1/suscriptores", params={"user_id": f"eq.{user_id}"},
                            json={"bienvenida_enviada": True}, headers={"Prefer": "return=minimal"}, timeout=30)
        if r.status_code >= 400:
            aviso(f"No pude marcar la bienvenida en Supabase: {r.status_code} {r.text[:160]}")


class Local:
    """Sin Supabase: le manda todo a los emails de EMAIL_TO (o al mismo Gmail)."""
    modo = "local"
    ARCHIVO = DATA / "avisados_local.json"

    def __init__(self, para: str, usuario: str):
        from .emailer import destinatarios
        self.lista = destinatarios(para, usuario) if (para or usuario) else []
        self.datos = leer_json(self.ARCHIVO, {})

    def suscriptores(self) -> List[dict]:
        return [{"id": e.lower(), "email": e, "nombre": "", "destinos": [], "bienvenida": True, "token_baja": None}
                for e in self.lista]

    def avisos(self) -> Dict[str, Dict[str, dict]]:
        return self.datos

    def guardar_avisos(self, user_id: str, avisos: Dict[str, dict], claves: List[str]) -> None:
        self.datos[user_id] = avisos
        guardar_json(self.ARCHIVO, self.datos)

    def marcar_bienvenida(self, user_id: str) -> None:
        pass


def conectar():
    url, secreta = env("SUPABASE_URL"), env("SUPABASE_SECRET_KEY")
    if url and secreta:
        return Supabase(url, secreta)
    return Local(env("EMAIL_TO"), env("GMAIL_USER"))
