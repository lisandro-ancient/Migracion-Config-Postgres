"""Registro local (SQLite) de todo lo que ejecuta el proyecto. El dashboard
solo lee de aquí (y de la evidencia en runs/); nunca recalcula por su cuenta.

Cuatro tablas:

- ``corridas``      una por tabla procesada (validación o migración de una tabla).
- ``trabajos``      un trabajo de migración (``migrar-todo``): agrupa corridas y
                    lleva el progreso en vivo (tabla actual, paso actual).
- ``comparaciones`` una comparación diferencial Firebird ↔ PostgreSQL.
- ``pruebas``       una ejecución de una suite de pytest lanzada desde el panel o el MCP.

Vive en un archivo local, nunca en la base CONFIG ni en PostgreSQL de destino:
es metadata de control, no datos migrados.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .rutas import ruta_ledger

ESQUEMA = """
CREATE TABLE IF NOT EXISTS corridas (
    run_id          TEXT PRIMARY KEY,
    fuente          TEXT NOT NULL,
    tabla           TEXT NOT NULL,
    modo            TEXT NOT NULL,  -- 'fixture' | 'firebird'
    estado          TEXT NOT NULL DEFAULT 'en_progreso',  -- 'en_progreso' | 'ok' | 'fail' | 'error'
    iniciado_en     REAL NOT NULL,
    terminado_en    REAL,
    filas_entrada   INTEGER,
    filas_salida    INTEGER,
    filas_falla     INTEGER,
    detalle_json    TEXT
);
CREATE TABLE IF NOT EXISTS trabajos (
    job_id          TEXT PRIMARY KEY,
    fuente          TEXT NOT NULL,
    modo            TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'en_progreso',  -- 'en_progreso' | 'ok' | 'fail' | 'error'
    iniciado_en     REAL NOT NULL,
    terminado_en    REAL,
    tablas_total    INTEGER NOT NULL DEFAULT 0,
    tablas_ok       INTEGER NOT NULL DEFAULT 0,
    tablas_fail     INTEGER NOT NULL DEFAULT 0,
    filas_origen    INTEGER NOT NULL DEFAULT 0,
    filas_migradas  INTEGER NOT NULL DEFAULT 0,
    tabla_actual    TEXT,
    paso_actual     TEXT,
    comparacion_id  TEXT,
    detalle_json    TEXT
);
CREATE TABLE IF NOT EXISTS comparaciones (
    comparacion_id  TEXT PRIMARY KEY,
    fuente          TEXT NOT NULL,
    modo            TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'en_progreso',
    iniciado_en     REAL NOT NULL,
    terminado_en    REAL,
    filas_origen    INTEGER,
    filas_destino   INTEGER,
    coinciden       INTEGER,
    diferentes      INTEGER,
    faltantes       INTEGER,
    sobrantes       INTEGER,
    rechazadas      INTEGER,
    detalle_json    TEXT
);
CREATE TABLE IF NOT EXISTS pruebas (
    prueba_id       TEXT PRIMARY KEY,
    suite           TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'en_progreso',
    iniciado_en     REAL NOT NULL,
    terminado_en    REAL,
    pasaron         INTEGER,
    fallaron        INTEGER,
    saltadas        INTEGER,
    errores         INTEGER,
    detalle_json    TEXT
);
"""

# Columnas agregadas después de la primera versión del ledger: se añaden a
# ledgers existentes sin perder su historial.
_COLUMNAS_TARDIAS = {"corridas": {"tipo": "TEXT NOT NULL DEFAULT 'validacion'", "job_id": "TEXT"}}


@contextmanager
def _conexion() -> Iterator[sqlite3.Connection]:
    ruta = ruta_ledger()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript(ESQUEMA)
    for tabla, columnas in _COLUMNAS_TARDIAS.items():
        existentes = {fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})")}
        for columna, definicion in columnas.items():
            if columna not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _nuevo_id() -> str:
    return uuid.uuid4().hex[:12]


def _json(valor: dict | None) -> str | None:
    return json.dumps(valor, ensure_ascii=False, default=str) if valor is not None else None


def _dicts(filas) -> list[dict[str, Any]]:
    return [dict(f) for f in filas]


def _actualizar(tabla: str, llave: str, valor_llave: str, campos: dict[str, Any]) -> None:
    if "detalle" in campos:
        campos["detalle_json"] = _json(campos.pop("detalle"))
    asignaciones = ", ".join(f"{c} = ?" for c in campos)
    with _conexion() as conn:
        conn.execute(f"UPDATE {tabla} SET {asignaciones} WHERE {llave} = ?", (*campos.values(), valor_llave))


# --- corridas -----------------------------------------------------------------


def iniciar_corrida(fuente: str, tabla: str, modo: str, tipo: str = "validacion", job_id: str | None = None) -> str:
    """``tipo``: 'validacion' (solo extraer + validar) o 'migracion' (además carga a PostgreSQL)."""
    run_id = _nuevo_id()
    with _conexion() as conn:
        conn.execute(
            "INSERT INTO corridas (run_id, fuente, tabla, modo, tipo, job_id, iniciado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, fuente, tabla, modo, tipo, job_id, time.time()),
        )
    return run_id


def finalizar_corrida(
    run_id: str,
    *,
    estado: str,
    filas_entrada: int | None = None,
    filas_salida: int | None = None,
    filas_falla: int | None = None,
    detalle: dict[str, Any] | None = None,
) -> None:
    _actualizar(
        "corridas",
        "run_id",
        run_id,
        {
            "estado": estado,
            "terminado_en": time.time(),
            "filas_entrada": filas_entrada,
            "filas_salida": filas_salida,
            "filas_falla": filas_falla,
            "detalle": detalle,
        },
    )


def listar_corridas(
    fuente: str | None = None,
    tabla: str | None = None,
    limite: int = 100,
    job_id: str | None = None,
    estados: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    condiciones, parametros = [], []
    for columna, valor in (("fuente", fuente), ("tabla", tabla), ("job_id", job_id)):
        if valor:
            condiciones.append(f"{columna} = ?")
            parametros.append(valor)
    if estados:
        condiciones.append(f"estado IN ({', '.join('?' * len(estados))})")
        parametros += list(estados)
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    with _conexion() as conn:
        filas = conn.execute(
            f"SELECT * FROM corridas {where} ORDER BY iniciado_en DESC LIMIT ?", (*parametros, limite)
        ).fetchall()
    return _dicts(filas)


def obtener_corrida(run_id: str) -> dict[str, Any] | None:
    with _conexion() as conn:
        fila = conn.execute("SELECT * FROM corridas WHERE run_id = ?", (run_id,)).fetchone()
    return dict(fila) if fila else None


# --- trabajos -----------------------------------------------------------------


def iniciar_trabajo(fuente: str, modo: str, tablas_total: int) -> str:
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + _nuevo_id()[:4]
    with _conexion() as conn:
        conn.execute(
            "INSERT INTO trabajos (job_id, fuente, modo, iniciado_en, tablas_total, paso_actual) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, fuente, modo, time.time(), tablas_total, "conectando"),
        )
    return job_id


def actualizar_trabajo(job_id: str, **campos: Any) -> None:
    _actualizar("trabajos", "job_id", job_id, campos)


def finalizar_trabajo(job_id: str, *, estado: str, detalle: dict[str, Any] | None = None, **campos: Any) -> None:
    _actualizar(
        "trabajos",
        "job_id",
        job_id,
        {"estado": estado, "terminado_en": time.time(), "tabla_actual": None, "paso_actual": None, "detalle": detalle, **campos},
    )


def listar_trabajos(limite: int = 50) -> list[dict[str, Any]]:
    with _conexion() as conn:
        return _dicts(conn.execute("SELECT * FROM trabajos ORDER BY iniciado_en DESC LIMIT ?", (limite,)).fetchall())


def obtener_trabajo(job_id: str) -> dict[str, Any] | None:
    with _conexion() as conn:
        fila = conn.execute("SELECT * FROM trabajos WHERE job_id = ?", (job_id,)).fetchone()
    return dict(fila) if fila else None


def marcar_trabajos_interrumpidos() -> int:
    """Un trabajo, comparación o corrida de pruebas 'en_progreso' de un proceso
    que ya no existe (p. ej. el panel se reinició a mitad) nunca va a terminar:
    se marca como error. Se llama al arrancar el panel."""
    mensaje = json.dumps({"error": "Interrumpido: el proceso que lo ejecutaba se detuvo."}, ensure_ascii=False)
    total = 0
    with _conexion() as conn:
        total += conn.execute(
            "UPDATE trabajos SET estado = 'error', terminado_en = ?, paso_actual = NULL, detalle_json = ? WHERE estado = 'en_progreso'",
            (time.time(), mensaje),
        ).rowcount
        for tabla in ("comparaciones", "pruebas", "corridas"):
            total += conn.execute(
                f"UPDATE {tabla} SET estado = 'error', terminado_en = ?, detalle_json = ? WHERE estado = 'en_progreso'",
                (time.time(), mensaje),
            ).rowcount
    return total


# --- comparaciones diferenciales ------------------------------------------------


def iniciar_comparacion(fuente: str, modo: str) -> str:
    comparacion_id = _nuevo_id()
    with _conexion() as conn:
        conn.execute(
            "INSERT INTO comparaciones (comparacion_id, fuente, modo, iniciado_en) VALUES (?, ?, ?, ?)",
            (comparacion_id, fuente, modo, time.time()),
        )
    return comparacion_id


def finalizar_comparacion(comparacion_id: str, *, estado: str, detalle: dict[str, Any] | None = None, **totales: Any) -> None:
    _actualizar(
        "comparaciones",
        "comparacion_id",
        comparacion_id,
        {"estado": estado, "terminado_en": time.time(), "detalle": detalle, **totales},
    )


def listar_comparaciones(limite: int = 20) -> list[dict[str, Any]]:
    with _conexion() as conn:
        return _dicts(conn.execute("SELECT * FROM comparaciones ORDER BY iniciado_en DESC LIMIT ?", (limite,)).fetchall())


def obtener_comparacion(comparacion_id: str) -> dict[str, Any] | None:
    with _conexion() as conn:
        fila = conn.execute("SELECT * FROM comparaciones WHERE comparacion_id = ?", (comparacion_id,)).fetchone()
    return dict(fila) if fila else None


# --- pruebas ------------------------------------------------------------------


def iniciar_prueba(suite: str) -> str:
    prueba_id = _nuevo_id()
    with _conexion() as conn:
        conn.execute("INSERT INTO pruebas (prueba_id, suite, iniciado_en) VALUES (?, ?, ?)", (prueba_id, suite, time.time()))
    return prueba_id


def finalizar_prueba(prueba_id: str, *, estado: str, detalle: dict[str, Any] | None = None, **totales: Any) -> None:
    _actualizar("pruebas", "prueba_id", prueba_id, {"estado": estado, "terminado_en": time.time(), "detalle": detalle, **totales})


def listar_pruebas(limite: int = 50, suite: str | None = None) -> list[dict[str, Any]]:
    with _conexion() as conn:
        if suite:
            filas = conn.execute("SELECT * FROM pruebas WHERE suite = ? ORDER BY iniciado_en DESC LIMIT ?", (suite, limite))
        else:
            filas = conn.execute("SELECT * FROM pruebas ORDER BY iniciado_en DESC LIMIT ?", (limite,))
        return _dicts(filas.fetchall())


# --- agregados para el panel ----------------------------------------------------


def resumen() -> dict[str, Any]:
    with _conexion() as conn:
        filas = _dicts(conn.execute("SELECT * FROM corridas").fetchall())
    duracion = sum(f["terminado_en"] - f["iniciado_en"] for f in filas if f["terminado_en"] is not None)
    ultima_migracion: dict[str, str] = {}
    for f in sorted(filas, key=lambda f: f["iniciado_en"]):
        if f["tipo"] == "migracion":
            ultima_migracion[f"{f['fuente']}.{f['tabla']}"] = f["estado"]
    return {
        "total_corridas": len(filas),
        "duracion_total_seg": round(duracion, 2),
        "tablas_migradas_ok": sorted(t for t, e in ultima_migracion.items() if e == "ok"),
    }


def actividad_reciente(limite: int = 12) -> list[dict[str, Any]]:
    """Eventos terminados de las cuatro tablas, del más reciente al más viejo."""
    eventos: list[dict[str, Any]] = []
    for c in listar_corridas(limite=limite):
        eventos.append(
            {
                "cuando": c["terminado_en"] or c["iniciado_en"],
                "tipo": c["tipo"],
                "estado": c["estado"],
                "texto": f"{'Migración' if c['tipo'] == 'migracion' else 'Validación'} de {c['fuente']}.{c['tabla']}",
                "enlace": f"/corrida/{c['run_id']}",
            }
        )
    for t in listar_trabajos(limite=limite):
        eventos.append(
            {
                "cuando": t["terminado_en"] or t["iniciado_en"],
                "tipo": "trabajo",
                "estado": t["estado"],
                "texto": f"Trabajo de migración {t['job_id']} — {t['tablas_ok']}/{t['tablas_total']} tablas",
                "enlace": f"/jobs/{t['job_id']}",
            }
        )
    for c in listar_comparaciones(limite=limite):
        eventos.append(
            {
                "cuando": c["terminado_en"] or c["iniciado_en"],
                "tipo": "comparacion",
                "estado": c["estado"],
                "texto": f"Comparación diferencial — {c['coinciden'] or 0} filas coincidentes",
                "enlace": "/data",
            }
        )
    from .pruebas import SUITES

    for p in listar_pruebas(limite=limite):
        eventos.append(
            {
                "cuando": p["terminado_en"] or p["iniciado_en"],
                "tipo": "prueba",
                "estado": p["estado"],
                "texto": f"{SUITES.get(p['suite'], 'Todas las pruebas')} — {p['pasaron'] or 0} aprobadas, {p['fallaron'] or 0} fallidas",
                "enlace": "/tests",
            }
        )
    return sorted(eventos, key=lambda e: e["cuando"], reverse=True)[:limite]
