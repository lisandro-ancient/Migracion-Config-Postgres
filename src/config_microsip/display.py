"""Vistas legibles (rich) de entradas, transformaciones, esquema y reporte.
Cada función devuelve el objeto renderizable; no imprime por su cuenta."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .manifiesto import Manifiesto
from .reglas.motor import ErrorDeTransformacion, normalizar_fila

console = Console()


def _marca(ok: bool) -> Text:
    return Text("✓", style="bold green") if ok else Text("✗", style="bold red")


def tabla_entradas_crudas(manifiesto: Manifiesto, filas: Sequence[Mapping[str, Any]], limite: int = 10) -> Table:
    columnas = [c.origen for c in manifiesto.campos][:10]
    tabla = Table(title=f"Entradas crudas de {manifiesto.tabla_origen} (primeras {min(limite, len(filas))} de {len(filas)})")
    for columna in columnas:
        tabla.add_column(columna, overflow="fold")
    for fila in filas[:limite]:
        tabla.add_row(*("" if fila.get(c) is None else str(fila.get(c)) for c in columnas))
    return tabla


def panel_comparacion_entrada_salida(manifiesto: Manifiesto, fila_cruda: Mapping[str, Any]) -> Panel:
    llave = manifiesto.valor_llave_crudo(fila_cruda)
    antes = Table(title="Antes (crudo)", show_header=False, box=None)
    antes.add_column(style="dim")
    antes.add_column()
    for clave, valor in fila_cruda.items():
        antes.add_row(clave, "" if valor is None else repr(valor))
    try:
        resultado = normalizar_fila(manifiesto, fila_cruda)
    except ErrorDeTransformacion as exc:
        cuerpo = Group(antes, Text(""), Text(f"RECHAZADO: {exc}", style="bold red"))
        return Panel(cuerpo, title=f"{manifiesto.nombre_llave}={llave} — RECHAZADO", border_style="red")
    despues = Table(title="Después (normalizado)", show_header=False, box=None)
    despues.add_column(style="dim")
    despues.add_column()
    for campo, valor in resultado.items():
        despues.add_row(campo, repr(valor))
    return Panel(Group(antes, Text(""), despues), title=f"{manifiesto.nombre_llave}={llave} — ACEPTADO", border_style="green")


def tabla_reporte_validacion(reporte: Mapping[str, Any]) -> Table:
    tabla = Table(title=f"Reporte de validación (modo {reporte.get('modo')})")
    tabla.add_column("Verificación")
    tabla.add_column("Resultado", justify="center")
    tabla.add_column("Detalle", overflow="fold")
    for v in reporte.get("verificaciones", []):
        tabla.add_row(
            v.get("verificacion", "?"), _marca(v.get("ok")), str({k: x for k, x in v.items() if k not in ("verificacion", "ok")})
        )
    tabla.add_row(
        "TOTAL",
        _marca(bool(reporte.get("ok_general"))),
        f"aceptadas={reporte.get('filas_aceptadas')}, rechazadas={reporte.get('filas_rechazadas')}",
    )
    return tabla


def tabla_migracion_todo(resultado: Mapping[str, Any]) -> Table:
    tabla = Table(title=f"Migración a PostgreSQL — fuente {resultado['fuente']} (orden padre → hijo)")
    for encabezado in ("#", "Tabla", "Resultado", "Filas cargadas", "run_id", "Detalle"):
        tabla.add_column(encabezado, overflow="fold")
    for i, t in enumerate(resultado["tablas"], 1):
        detalle = t.get("error") or (", ".join(t.get("fallas") or []) or ("" if t.get("cargado") else "no se cargó"))
        tabla.add_row(str(i), t["tabla"], _marca(t["ok"]), str(t.get("filas", "—")), t.get("run_id", "—"), detalle)
    tabla.add_row("", "TOTAL", _marca(resultado["ok_general"]), "", "", "")
    return tabla


def tabla_listado_tablas(tablas: Sequence[Mapping[str, Any]]) -> Table:
    tabla = Table(title=f"Tablas de usuario en la base conectada ({len(tablas)})")
    tabla.add_column("Tabla")
    con_conteo = any("filas" in t for t in tablas)
    if con_conteo:
        tabla.add_column("Filas", justify="right")
    for t in tablas:
        tabla.add_row(t["tabla"], *([str(t.get("filas", ""))] if con_conteo else []))
    return tabla


def tabla_descripcion(descripcion: Mapping[str, Any]) -> Table:
    tabla = Table(
        title=f"{descripcion['tabla']} — {descripcion.get('filas')} filas — PK: {', '.join(descripcion['llave_primaria']) or '(ninguna)'}"
    )
    for encabezado in ("#", "Columna", "Tipo", "Nulo", "Charset", "PK"):
        tabla.add_column(encabezado)
    for c in descripcion["columnas"]:
        tabla.add_row(
            str(c["posicion"]),
            c["nombre"],
            c["tipo"],
            "sí" if c["nulo_permitido"] else "no",
            c.get("charset") or "",
            "●" if c.get("es_llave_primaria") else "",
        )
    return tabla
