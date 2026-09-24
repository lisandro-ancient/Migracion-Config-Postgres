"""Extracción de datos, parametrizada por manifiesto. Dos orígenes, misma
forma de salida (lista de dicts con las claves ``origen`` del manifiesto):

- **fixture**: el snapshot JSON declarado en el manifiesto, capturado antes
  con ``capturar_fixtures`` (solo lectura). Es lo que usan las pruebas y las
  corridas reproducibles.
- **Firebird real**: la base CONFIG en vivo, vía conexion_solo_lectura().

Nunca se usa ``ORDER BY`` sobre tablas de datos: con columnas ISO8859_1 y sin
el módulo INTL instalado, Firebird falla al construir la clave de orden. El
orden estable (por llave primaria) se aplica en Python.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .conexion import conexion_solo_lectura, identificador_seguro
from .config import ConfigFirebird
from .manifiesto import CatalogoManifiesto, Manifiesto


class FixtureInexistente(FileNotFoundError):
    pass


def _leer_fixture(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        raise FixtureInexistente(
            f"No existe el snapshot {ruta}. Captúralo con "
            "'python -m config_microsip.cli capturar --fuente <f> --tabla <t>' o usa --firebird-real."
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


def _clave_orden(valor: Any) -> tuple:
    if valor is None:
        return (2, 0, "")
    if isinstance(valor, (int, Decimal, float)) and not isinstance(valor, bool):
        return (0, valor, "")
    return (1, 0, str(valor))


def _orden_estable(filas: list[dict[str, Any]], claves: list[str]) -> list[dict[str, Any]]:
    """Orden por llave primaria aplicado en Python (ver docstring del módulo)."""
    return sorted(filas, key=lambda f: tuple(_clave_orden(f.get(c)) for c in claves))


def _leer_valor(valor: Any) -> Any:
    """firebird-driver entrega los BLOB de texto grandes como un lector en
    streaming en vez de str; se materializan aquí para que el resto del
    pipeline vea siempre valores simples."""
    if hasattr(valor, "read") and callable(valor.read):
        try:
            return valor.read()
        finally:
            valor.close()
    return valor


def _filas_como_dicts(cur, sql: str, columnas: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(columnas, (_leer_valor(v) for v in fila), strict=True)) for fila in cur.ejecutar(sql).filas()]


def _select(tabla: str, columnas: list[str]) -> str:
    return f"SELECT {', '.join(identificador_seguro(c) for c in columnas)} FROM {identificador_seguro(tabla)}"


# --- tabla principal ---------------------------------------------------------


def extraer_filas_desde_fixture(manifiesto: Manifiesto) -> list[dict[str, Any]]:
    return _leer_fixture(manifiesto.ruta_fixture())["filas"]


def conteo_origen_desde_fixture(manifiesto: Manifiesto) -> int | None:
    """COUNT(*) que se registró en la base al capturar el snapshot (``_meta``)."""
    return _leer_fixture(manifiesto.ruta_fixture()).get("_meta", {}).get("conteo_origen")


def extraer_desde_firebird(manifiesto: Manifiesto, config: ConfigFirebird | None = None) -> tuple[list[dict[str, Any]], int]:
    """Filas de la tabla principal + su COUNT(*), ambos leídos dentro de la
    misma transacción de solo lectura (misma foto de la base)."""
    columnas = [c.origen for c in manifiesto.campos]
    with conexion_solo_lectura(config) as cur:
        filas = _filas_como_dicts(cur, _select(manifiesto.tabla_origen, columnas), columnas)
        conteo = cur.ejecutar(f"SELECT COUNT(*) FROM {identificador_seguro(manifiesto.tabla_origen)}").escalar()
    return _orden_estable(filas, [c.origen for c in manifiesto.campos_llave()]), conteo


# --- catálogos ---------------------------------------------------------------


def extraer_catalogo(
    catalogo: CatalogoManifiesto, *, usar_firebird_real: bool, config: ConfigFirebird | None = None
) -> list[dict[str, Any]]:
    """Filas de un catálogo con las claves ``destino`` de su mapeo."""
    if catalogo.tipo == "derivado":
        return [dict(zip(catalogo.columnas, v, strict=True)) for v in catalogo.valores or []]
    mapeo = catalogo.mapeo()
    if usar_firebird_real:
        origenes = [o for o, _ in mapeo]
        with conexion_solo_lectura(config) as cur:
            crudas = _filas_como_dicts(cur, _select(catalogo.tabla, origenes), origenes)
    else:
        crudas = _leer_fixture(catalogo.ruta_fixture())["filas"]
    return [{destino: fila.get(origen) for origen, destino in mapeo} for fila in crudas]


# --- captura de snapshots ----------------------------------------------------


def _a_json(valor: Any) -> Any:
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ")
    if isinstance(valor, (date, time)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, bytes):
        return valor.hex()
    return str(valor)


def _escribir_snapshot(ruta: Path, meta: dict[str, Any], filas: list[dict[str, Any]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps({"_meta": meta, "filas": filas}, indent=2, ensure_ascii=False, default=_a_json) + "\n",
        encoding="utf-8",
    )


def capturar_fixtures(manifiesto: Manifiesto, config: ConfigFirebird | None = None) -> dict[str, Any]:
    """Lee de Firebird (solo lectura) la tabla principal y sus catálogos de
    tipo ``tabla`` y los guarda como snapshots en las rutas que declara el
    manifiesto. Sobrescribe el snapshot anterior: es una foto nueva."""
    config = config or ConfigFirebird.desde_entorno()
    capturado_en = datetime.now(UTC).isoformat(timespec="seconds")
    filas, conteo = extraer_desde_firebird(manifiesto, config)
    meta = {
        "fuente": manifiesto.fuente,
        "tabla_origen": manifiesto.tabla_origen,
        "columnas": [c.origen for c in manifiesto.campos],
        "conteo_origen": conteo,
        "capturado_en": capturado_en,
        "conexion": config.descripcion_segura(),
        "nota": "Capturado en una transacción de solo lectura (READ COMMITTED, READ ONLY) con conteo y filas en la misma transacción.",
    }
    _escribir_snapshot(manifiesto.ruta_fixture(), meta, filas)
    resumen: dict[str, Any] = {
        "tabla": {"ruta": str(manifiesto.ruta_fixture()), "filas": len(filas), "conteo_origen": conteo},
        "catalogos": [],
    }

    for catalogo in manifiesto.catalogos:
        if catalogo.tipo != "tabla":
            continue
        origenes = [o for o, _ in catalogo.mapeo()]
        with conexion_solo_lectura(config) as cur:
            filas_cat = _filas_como_dicts(cur, _select(catalogo.tabla, origenes), origenes)
        filas_cat = _orden_estable(filas_cat, origenes[:1])
        _escribir_snapshot(
            catalogo.ruta_fixture(),
            {
                "fuente": manifiesto.fuente,
                "tabla_origen": catalogo.tabla_origen,
                "columnas": origenes,
                "conteo_origen": len(filas_cat),
                "capturado_en": capturado_en,
                "conexion": config.descripcion_segura(),
            },
            filas_cat,
        )
        resumen["catalogos"].append({"catalogo": catalogo.nombre, "ruta": str(catalogo.ruta_fixture()), "filas": len(filas_cat)})
    return resumen
