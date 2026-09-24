"""Grafo de dependencias entre una tabla y sus catálogos, con ``graphlib`` de
la librería estándar (sin base de grafo: el problema son unas pocas tablas).

Nodos = catálogos + tabla principal; aristas = ``depende_de``. Responde en qué
orden se extraen las cosas y qué depende de qué, para el dashboard y el MCP.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

from .manifiesto import Manifiesto


class ErrorDeGrafo(ValueError):
    pass


def construir_grafo(manifiesto: Manifiesto) -> dict[str, list[str]]:
    grafo: dict[str, list[str]] = {c.nombre: [] for c in manifiesto.catalogos}
    grafo[manifiesto.tabla_destino] = list(manifiesto.depende_de)
    return grafo


def orden_de_extraccion(manifiesto: Manifiesto) -> list[str]:
    try:
        return list(TopologicalSorter(construir_grafo(manifiesto)).static_order())
    except CycleError as exc:
        raise ErrorDeGrafo(f"Dependencias cíclicas en el manifiesto de '{manifiesto.tabla_destino}': {exc}") from exc


def describir_grafo(manifiesto: Manifiesto) -> dict:
    grafo = construir_grafo(manifiesto)
    return {
        "nodos": [{"nombre": n, "tipo": "tabla_principal" if n == manifiesto.tabla_destino else "catalogo"} for n in grafo],
        "aristas": [{"desde": n, "hacia": d} for n, deps in grafo.items() for d in deps],
        "orden_de_extraccion": orden_de_extraccion(manifiesto),
    }
