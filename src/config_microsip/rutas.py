"""Rutas del proyecto, resueltas en tiempo de ejecución (no al importar).

El código vive siempre en este repositorio, pero los *datos* de trabajo
—manifiestos, fixtures, golden, evidencia de corridas y el ledger— cuelgan de
una raíz de datos que por defecto es la raíz del repositorio y que se puede
redirigir con ``CONFIG_MICROSIP_DATOS``. Las pruebas lo usan para trabajar
sobre una copia temporal sin ensuciar el repositorio, y sirve también para
apuntar a otra carpeta de manifiestos sin tocar código.
"""

from __future__ import annotations

import os
from pathlib import Path

RUTA_PROYECTO = Path(__file__).resolve().parent.parent.parent


def raiz_datos() -> Path:
    return Path(os.environ.get("CONFIG_MICROSIP_DATOS") or RUTA_PROYECTO).resolve()


def ruta_fuentes() -> Path:
    return raiz_datos() / "fuentes"


def ruta_runs() -> Path:
    return raiz_datos() / "runs"


def ruta_ledger() -> Path:
    return raiz_datos() / "runs.db"
