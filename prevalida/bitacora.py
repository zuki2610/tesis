"""Bitácora de eventos inmodificable (RF-12): cada entrada incluye el hash de la anterior,
de modo que cualquier alteración posterior rompe la cadena y es detectable."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone


class Bitacora:
    def __init__(self, ruta: str = ":memory:"):
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, ts TEXT, solicitud TEXT,"
                        " actor TEXT, evento TEXT, datos TEXT, hash_prev TEXT, hash TEXT)")

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

    def verificar(self) -> bool:
        prev = "0" * 64
        for ts, sol, actor, ev, datos, hp, h in self.db.execute(
                "SELECT ts, solicitud, actor, evento, datos, hash_prev, hash FROM eventos ORDER BY id"):
            cuerpo = json.dumps({"ts": ts, "solicitud": sol, "actor": actor, "evento": ev,
                                 "datos": json.loads(datos), "prev": prev}, sort_keys=True, ensure_ascii=False, default=str)
            if hp != prev or hashlib.sha256(cuerpo.encode()).hexdigest() != h:
                return False
            prev = h
        return True
