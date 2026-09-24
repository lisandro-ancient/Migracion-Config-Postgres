"""Comparación diferencial Firebird ↔ PostgreSQL, independiente de cualquier
corrida de migración: vuelve a leer el origen y el destino y clasifica cada
fila por su llave.

- **coincide**  la llave existe en ambos y todas las columnas son iguales.
- **diferente** la llave existe en ambos pero al menos una columna difiere.
- **faltante**  está en el origen (y pasa las reglas) pero no en PostgreSQL.
- **sobrante**  está en PostgreSQL pero ya no en el origen.
- **rechazada** el origen la tiene pero el motor de reglas la rechaza: por
  diseño no debe estar en PostgreSQL, así que no cuenta como faltante.

También compara el esquema: las columnas de la tabla en PostgreSQL deben ser
exactamente las del manifiesto.

Es lo que alimenta la dona "Data Comparison" y la vista "Data Overview" del
panel; el trabajo de migración la corre al final de cada ejecución.
"""

from __future__ import annotations

import json
from typing import Any

from . import ledger
from .harness_extraccion import construir_candidato
from .harness_migracion import _leer_tabla, conectar, orden_de_migracion, tabla_existe
from .manifiesto import Manifiesto, cargar_manifiesto
from .rutas import ruta_runs

MUESTRA_DIFERENCIAS = 20


def _columnas_postgres(conn, manifiesto: Manifiesto) -> list[str]:
    return [
        f[0]
        for f in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (manifiesto.fuente, manifiesto.tabla_destino),
        ).fetchall()
    ]


def comparar_tabla(conn, manifiesto: Manifiesto, *, usar_firebird_real: bool) -> dict[str, Any]:
    resultado = construir_candidato(manifiesto, usar_firebird_real=usar_firebird_real)
    esperado = [c.destino for c in manifiesto.campos]
    existe = tabla_existe(conn, manifiesto)
    columnas_pg = _columnas_postgres(conn, manifiesto) if existe else []
    en_pg = _leer_tabla(conn, manifiesto) if existe and set(esperado) <= set(columnas_pg) else []

    origen = {manifiesto.valor_llave(f): f for f in resultado.candidato}
    destino = {manifiesto.valor_llave(f): f for f in en_pg}
    coinciden, diferencias = 0, []
    for llave, fila in origen.items():
        otra = destino.get(llave)
        if otra is None:
            continue
        distintas = {c: {"origen": fila[c], "postgres": otra.get(c)} for c in esperado if fila[c] != otra.get(c)}
        if distintas:
            diferencias.append({"llave": llave, "columnas": distintas})
        else:
            coinciden += 1
    faltantes = sorted(set(origen) - set(destino))
    sobrantes = sorted(set(destino) - set(origen))
    esquema_ok = existe and columnas_pg == esperado
    return {
        "tabla": manifiesto.tabla_destino,
        "tabla_origen": manifiesto.tabla_origen,
        "tabla_en_postgres": existe,
        "esquema": {"ok": esquema_ok, "esperadas": esperado, "en_postgres": columnas_pg},
        "filas_origen": len(resultado.filas_crudas),
        "filas_destino": len(en_pg),
        "rechazadas": len(resultado.rechazadas),
        "coinciden": coinciden,
        "diferentes": len(diferencias),
        "faltantes": len(faltantes),
        "sobrantes": len(sobrantes),
        "muestra_diferencias": diferencias[:MUESTRA_DIFERENCIAS],
        "muestra_faltantes": faltantes[:MUESTRA_DIFERENCIAS],
        "muestra_sobrantes": sobrantes[:MUESTRA_DIFERENCIAS],
        "ok": esquema_ok and not diferencias and not faltantes and not sobrantes,
    }


def comparar_fuente(
    fuente: str, *, usar_firebird_real: bool = False, tablas: list[str] | None = None, comparacion_id: str | None = None
) -> dict[str, Any]:
    """Compara todas las tablas (o las indicadas), registra la comparación en el
    ledger y guarda el detalle en runs/diferencial/<id>.json. ``comparacion_id``
    permite registrarla antes de lanzarla en segundo plano (el panel la muestra
    como 'en curso' desde el primer instante)."""
    modo = "firebird" if usar_firebird_real else "fixture"
    comparacion_id = comparacion_id or ledger.iniciar_comparacion(fuente, modo)
    try:
        por_tabla = []
        with conectar() as conn:
            for tabla in tablas or orden_de_migracion(fuente):
                try:
                    por_tabla.append(
                        comparar_tabla(conn, cargar_manifiesto(fuente, tabla), usar_firebird_real=usar_firebird_real)
                    )
                except Exception as exc:
                    por_tabla.append(
                        {
                            "tabla": tabla,
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                            **{
                                k: 0
                                for k in (
                                    "filas_origen",
                                    "filas_destino",
                                    "rechazadas",
                                    "coinciden",
                                    "diferentes",
                                    "faltantes",
                                    "sobrantes",
                                )
                            },
                        }
                    )
    except Exception as exc:
        ledger.finalizar_comparacion(comparacion_id, estado="error", detalle={"error": f"{type(exc).__name__}: {exc}"})
        raise

    totales = {
        k: sum(t[k] for t in por_tabla)
        for k in ("filas_origen", "filas_destino", "coinciden", "diferentes", "faltantes", "sobrantes", "rechazadas")
    }
    ok = all(t["ok"] for t in por_tabla)
    informe = {
        "comparacion_id": comparacion_id,
        "fuente": fuente,
        "modo": modo,
        "ok": ok,
        "totales": totales,
        "tablas": por_tabla,
    }
    ruta = ruta_runs() / "diferencial" / f"{comparacion_id}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(informe, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    ledger.finalizar_comparacion(
        comparacion_id,
        estado="ok" if ok else "fail",
        detalle={
            "tablas": [
                {
                    k: t.get(k)
                    for k in (
                        "tabla",
                        "ok",
                        "error",
                        "filas_origen",
                        "filas_destino",
                        "coinciden",
                        "diferentes",
                        "faltantes",
                        "sobrantes",
                        "rechazadas",
                    )
                }
                | {"esquema_ok": t.get("esquema", {}).get("ok")}
                for t in por_tabla
            ]
        },
        **totales,
    )
    return informe


def leer_informe(comparacion_id: str) -> dict[str, Any] | None:
    ruta = ruta_runs() / "diferencial" / f"{comparacion_id}.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
