"""Bitácora de eventos (RF-12) que permite detectar alteraciones.

Cada entrada incluye el hash de la anterior (encadenamiento SHA-256). El encadenamiento
por sí solo detecta la modificación de un evento intermedio, pero NO detecta que se
borren los últimos eventos ni que se reescriba la cadena completa. Para eso, el hash
final y el número de eventos se "anclan" periódicamente fuera de la base de datos:
en el prototipo, mediante un HMAC con una clave que la base de datos no conoce; en
producción, mediante un sello de tiempo de un tercero o almacenamiento de una sola
escritura (WORM). Los eventos posteriores al último ancla solo están protegidos por
el encadenamiento hasta el ancla siguiente.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone


class Bitacora:
    def __init__(self, ruta: str = ":memory:", clave_ancla: bytes | None = None):
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, ts TEXT, solicitud TEXT,"
                        " actor TEXT, evento TEXT, datos TEXT, hash_prev TEXT, hash TEXT)")
        self._clave = clave_ancla or b"clave-de-prueba-fuera-de-la-base"

    def _ultimo_hash(self) -> str:
        r = self.db.execute("SELECT hash FROM eventos ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else "0" * 64

    def registrar(self, solicitud: str, actor: str, evento: str, datos: dict) -> str:
        ts = datetime.now(timezone.utc).isoformat()
        prev = self._ultimo_hash()
        cuerpo = json.dumps({"ts": ts, "solicitud": solicitud, "actor": actor, "evento": evento,
                             "datos": datos, "prev": prev}, sort_keys=True, ensure_ascii=False, default=str)
        h = hashlib.sha256(cuerpo.encode()).hexdigest()
        self.db.execute("INSERT INTO eventos (ts, solicitud, actor, evento, datos, hash_prev, hash) VALUES (?,?,?,?,?,?,?)",
                        (ts, solicitud, actor, evento, json.dumps(datos, ensure_ascii=False, default=str), prev, h))
        self.db.commit()
        return h

    def ancla(self) -> dict:
        """Ancla externa: número de eventos y hash final, autenticados con HMAC."""
        n = self.db.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
        h = self._ultimo_hash()
        firma = hmac.new(self._clave, f"{n}:{h}".encode(), hashlib.sha256).hexdigest()
        return {"n": n, "hash": h, "hmac": firma}

    def verificar(self, ancla: dict | None = None) -> bool:
        prev = "0" * 64
        n = 0
        for ts, sol, actor, ev, datos, hp, h in self.db.execute(
                "SELECT ts, solicitud, actor, evento, datos, hash_prev, hash FROM eventos ORDER BY id"):
            cuerpo = json.dumps({"ts": ts, "solicitud": sol, "actor": actor, "evento": ev,
                                 "datos": json.loads(datos), "prev": prev}, sort_keys=True, ensure_ascii=False, default=str)
            if hp != prev or hashlib.sha256(cuerpo.encode()).hexdigest() != h:
                return False
            prev = h
            n += 1
        if ancla is None:
            return True
        firma_ok = hmac.compare_digest(
            ancla["hmac"], hmac.new(self._clave, f"{ancla['n']}:{ancla['hash']}".encode(), hashlib.sha256).hexdigest())
        if not firma_ok or n < ancla["n"]:
            return False
        # El evento número n del ancla debe tener el hash anclado.
        fila = self.db.execute("SELECT hash FROM eventos ORDER BY id LIMIT 1 OFFSET ?", (ancla["n"] - 1,)).fetchone()
        return ancla["n"] == 0 or (fila is not None and fila[0] == ancla["hash"])
