"""Motor de reglas: aplica las primitivas a una fila cruda según lo que
declare un manifiesto. Devuelve un dict con las claves ``destino``.

Regla transversal del motor: si la columna declara ``nulo_permitido: true`` y
el valor llega NULL, el resultado es NULL sin invocar la primitiva. Si no lo
permite, la primitiva recibe el NULL y rechaza la fila con un motivo explícito.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..manifiesto import CampoManifiesto, Manifiesto
from . import primitivas
from .primitivas import ErrorDeTransformacion

__all__ = ["ErrorDeTransformacion", "aplicar_regla", "normalizar_fila"]


def aplicar_regla(campo: CampoManifiesto, valor: Any, manifiesto: Manifiesto) -> Any:
    regla, nombre = campo.regla, campo.destino
    if regla == "texto":
        return primitivas.normalizar_texto(valor, campo=nombre, nulo_permitido=campo.nulo_permitido)
    if valor is None and campo.nulo_permitido:
        return None
    if regla == "bandera_sn":
        return primitivas.normalizar_bandera_sn(valor, campo=nombre)
    if regla == "booleano":
        return primitivas.normalizar_booleano(valor, campo=nombre)
    if regla == "catalogo_normalizado":
        dominio = manifiesto.catalogo(campo.catalogo_dominio).dominio()
        return primitivas.normalizar_codigo_catalogo(valor, campo=nombre, dominio=dominio)
    if regla == "decimal":
        return primitivas.normalizar_decimal(valor, campo=nombre)
    if regla == "decimal_con_signo":
        return primitivas.normalizar_decimal(valor, campo=nombre, minimo=None)
    if regla == "entero":
        return primitivas.normalizar_entero(valor, campo=nombre)
    if regla == "fecha":
        return primitivas.normalizar_fecha(valor, campo=nombre)
    if regla == "hora":
        return primitivas.normalizar_hora(valor, campo=nombre)
    if regla == "timestamp":
        return primitivas.normalizar_timestamp(valor, campo=nombre)
    raise ValueError(f"campo '{nombre}': regla de normalización desconocida '{regla}'")


def normalizar_fila(manifiesto: Manifiesto, fila: Mapping[str, Any]) -> dict[str, Any]:
    """Aplica todas las reglas del manifiesto a una fila cruda. Lanza
    ErrorDeTransformacion identificando la llave primaria y el campo."""
    try:
        resultado = {c.destino: aplicar_regla(c, fila.get(c.origen), manifiesto) for c in manifiesto.campos}
    except ErrorDeTransformacion as exc:
        raise ErrorDeTransformacion(f"{manifiesto.nombre_llave}={manifiesto.valor_llave_crudo(fila)}: {exc}") from exc
    return resultado
