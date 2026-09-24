"""Harness de Extracción: dado un manifiesto, construye el "candidato" —
extrae la tabla principal y sus catálogos (en el orden que dicta el grafo) y
normaliza cada fila con el motor de reglas.

Equivale al Harness de Migración del proyecto hermano, sin PostgreSQL: el
candidato vive en memoria y el Harness de Testing lo escribe como evidencia.
Este harness solo construye; nunca decide si el resultado es correcto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conexion import identificador_seguro
from .config import ConfigFirebird
from .extract import (
    conteo_origen_desde_fixture,
    extraer_catalogo,
    extraer_desde_firebird,
    extraer_filas_desde_fixture,
)
from .grafo import orden_de_extraccion
from .manifiesto import Manifiesto
from .reglas.motor import ErrorDeTransformacion, normalizar_fila


@dataclass
class ResultadoExtraccion:
    modo: str  # 'fixture' | 'firebird'
    conteo_origen: int | None
    filas_crudas: list[dict[str, Any]] = field(default_factory=list)
    candidato: list[dict[str, Any]] = field(default_factory=list)
    rechazadas: list[dict[str, Any]] = field(default_factory=list)
    catalogos: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def construir_candidato(
    manifiesto: Manifiesto, *, usar_firebird_real: bool = False, config: ConfigFirebird | None = None
) -> ResultadoExtraccion:
    if usar_firebird_real:
        config = config or ConfigFirebird.desde_entorno()
    resultado: ResultadoExtraccion | None = None
    catalogos: dict[str, list[dict[str, Any]]] = {}

    for nodo in orden_de_extraccion(manifiesto):
        if nodo != manifiesto.tabla_destino:
            catalogos[nodo] = extraer_catalogo(manifiesto.catalogo(nodo), usar_firebird_real=usar_firebird_real, config=config)
            continue
        if usar_firebird_real:
            filas, conteo = extraer_desde_firebird(manifiesto, config)
            resultado = ResultadoExtraccion(modo="firebird", conteo_origen=conteo, filas_crudas=filas)
        else:
            filas = extraer_filas_desde_fixture(manifiesto)
            resultado = ResultadoExtraccion(
                modo="fixture", conteo_origen=conteo_origen_desde_fixture(manifiesto), filas_crudas=filas
            )

    if resultado is None:  # imposible si el grafo es válido: la tabla principal siempre es un nodo
        raise RuntimeError(f"El orden de extracción de {manifiesto.tabla_destino} no incluyó la tabla principal.")
    for fila in resultado.filas_crudas:
        try:
            resultado.candidato.append(normalizar_fila(manifiesto, fila))
        except ErrorDeTransformacion as exc:
            resultado.rechazadas.append({"llave": manifiesto.valor_llave_crudo(fila), "motivo": str(exc)})
    resultado.catalogos = catalogos
    return resultado


def describir_queries(manifiesto: Manifiesto) -> dict[str, Any]:
    """Las consultas literales que este harness ejecuta contra Firebird para
    un manifiesto (en modo --firebird-real), para la evidencia y el dashboard."""

    def select(tabla: str, columnas: list[str]) -> str:
        return f"SELECT {', '.join(identificador_seguro(c) for c in columnas)}\nFROM {identificador_seguro(tabla)}"

    return {
        "tabla_origen": manifiesto.tabla_origen,
        "tabla_destino": manifiesto.tabla_destino,
        "transaccion": "READ COMMITTED RECORD_VERSION, READ ONLY — siempre termina en ROLLBACK",
        "extraccion_sql": select(manifiesto.tabla_origen, [c.origen for c in manifiesto.campos])
        + "\n-- sin ORDER BY a propósito: el orden estable por llave primaria se aplica en Python",
        "conteo_sql": f"SELECT COUNT(*) FROM {identificador_seguro(manifiesto.tabla_origen)}",
        "catalogos_sql": [
            {
                "catalogo": c.nombre,
                "origen_datos": "valores declarados en el manifiesto" if c.tipo == "derivado" else f"tabla {c.tabla_origen}",
                "sql": None if c.tipo == "derivado" else select(c.tabla, [o for o, _ in c.mapeo()]),
            }
            for c in manifiesto.catalogos
        ],
    }
