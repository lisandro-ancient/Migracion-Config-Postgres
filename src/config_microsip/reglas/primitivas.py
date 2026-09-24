"""Primitivas de normalización: funciones puras, una por tipo de dato de
origen, reusables por cualquier manifiesto.

Principio heredado de ``migracion-firebird-postgres-clientes``: fallar
rápido, nunca un default silencioso. Si un dato no cumple, la fila se rechaza
con un motivo explícito; no se inventa un valor para que "pase". El manejo de
NULL permitido lo resuelve el motor (reglas/motor.py) antes de llegar aquí:
estas funciones solo ven NULL cuando la columna NO lo permite.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any


class ErrorDeTransformacion(ValueError):
    """Una fila de origen no puede normalizarse con garantías."""


def _no_nulo(valor: Any, campo: str) -> None:
    if valor is None:
        raise ErrorDeTransformacion(f"Campo obligatorio '{campo}' llegó nulo")


def normalizar_texto(valor: str | None, *, campo: str, nulo_permitido: bool) -> str | None:
    """Recorta el relleno de espacios de CHAR/VARCHAR sin tocar el contenido
    interno. Una cadena vacía tras recortar se trata como ausencia de dato."""
    if valor is None:
        if nulo_permitido:
            return None
        _no_nulo(valor, campo)
    texto = str(valor).strip()
    if texto == "":
        if nulo_permitido:
            return None
        raise ErrorDeTransformacion(f"Campo obligatorio '{campo}' llegó vacío tras recortar espacios")
    return texto


def normalizar_bandera_sn(valor: str | None, *, campo: str) -> bool:
    """Patrón CHAR(1) 'S'/'N' de MicroSIP -> booleano. Sin default para NULL
    ni para otros valores: requeriría una decisión de negocio explícita."""
    _no_nulo(valor, campo)
    valor_norm = str(valor).strip().upper()
    if valor_norm == "S":
        return True
    if valor_norm == "N":
        return False
    raise ErrorDeTransformacion(f"Bandera '{campo}' tiene valor no reconocido: {valor!r}")


def normalizar_booleano(valor: Any, *, campo: str) -> bool:
    _no_nulo(valor, campo)
    if isinstance(valor, bool):
        return valor
    if valor in (0, 1):
        return bool(valor)
    raise ErrorDeTransformacion(f"Booleano '{campo}' tiene valor no reconocido: {valor!r}")


def normalizar_codigo_catalogo(valor: str | None, *, campo: str, dominio: Mapping[str, str]) -> str:
    """Código de un catálogo pequeño (mayúsculas, sin espacios) validado contra
    el dominio que declara el manifiesto."""
    _no_nulo(valor, campo)
    codigo = str(valor).strip().upper()
    if codigo not in dominio:
        raise ErrorDeTransformacion(
            f"Campo de catálogo '{campo}' con código fuera del dominio conocido {sorted(dominio)}: {codigo!r}"
        )
    return codigo


def normalizar_decimal(valor: Any, *, campo: str, minimo: Decimal | None = Decimal("0")) -> Decimal:
    _no_nulo(valor, campo)
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError) as exc:
        raise ErrorDeTransformacion(f"Campo numérico '{campo}' no es un decimal válido: {valor!r}") from exc
    if not numero.is_finite():
        raise ErrorDeTransformacion(f"Campo numérico '{campo}' no es finito: {valor!r}")
    # Sin redondeo: se conserva la precisión exacta del origen (una tasa o un
    # porcentaje de CONFIG puede tener más de dos decimales).
    if minimo is not None and numero < minimo:
        raise ErrorDeTransformacion(f"Campo numérico '{campo}' es menor al mínimo permitido ({minimo}): {numero}")
    return numero


def normalizar_entero(valor: Any, *, campo: str) -> int:
    _no_nulo(valor, campo)
    if isinstance(valor, bool):
        raise ErrorDeTransformacion(f"Campo entero '{campo}' recibió un booleano: {valor!r}")
    try:
        numero = Decimal(str(valor).strip())
    except InvalidOperation as exc:
        raise ErrorDeTransformacion(f"Campo entero '{campo}' no es un entero válido: {valor!r}") from exc
    if numero != numero.to_integral_value():
        raise ErrorDeTransformacion(f"Campo entero '{campo}' tiene parte decimal: {valor!r}")
    return int(numero)


def normalizar_fecha(valor: Any, *, campo: str) -> date:
    _no_nulo(valor, campo)
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError as exc:
        raise ErrorDeTransformacion(f"Fecha '{campo}' no válida: {valor!r}") from exc


def normalizar_hora(valor: Any, *, campo: str) -> time:
    _no_nulo(valor, campo)
    if isinstance(valor, time):
        return valor
    try:
        return time.fromisoformat(str(valor))
    except ValueError as exc:
        raise ErrorDeTransformacion(f"Hora '{campo}' no válida: {valor!r}") from exc


def normalizar_timestamp(valor: Any, *, campo: str) -> datetime:
    _no_nulo(valor, campo)
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError as exc:
        raise ErrorDeTransformacion(f"Timestamp '{campo}' no válido: {valor!r}") from exc
