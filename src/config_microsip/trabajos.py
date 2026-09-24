"""Ejecución en segundo plano para el panel: un trabajo de migración, una
comparación diferencial o una suite de pruebas corren en un hilo y escriben su
progreso en el ledger; el panel lo lee por polling. Un solo trabajo pesado a la
vez por proceso (migración y comparación comparten el candado), para que dos
clics no carguen PostgreSQL en paralelo.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from . import ledger

_candado = threading.Lock()
_hilos: dict[str, threading.Thread] = {}


class TrabajoEnCurso(RuntimeError):
    pass


def ocupado() -> bool:
    return _candado.locked()


def _en_hilo(nombre: str, funcion: Callable[[], Any]) -> threading.Thread:
    if not _candado.acquire(blocking=False):
        raise TrabajoEnCurso("Ya hay una migración o comparación en curso; espera a que termine.")

    def ejecutar():
        try:
            funcion()
        except Exception:
            # El orquestador ya dejó el error registrado en el ledger; aquí solo
            # se deja rastro en el log del proceso, sin tumbar el hilo.
            logging.getLogger(__name__).exception("El trabajo en segundo plano %s terminó con error", nombre)
        finally:
            _candado.release()

    hilo = threading.Thread(target=ejecutar, name=nombre, daemon=True)
    _hilos[nombre] = hilo
    hilo.start()
    return hilo


def iniciar_migracion(fuente: str, *, usar_firebird_real: bool, permitir_borrador: bool, reset_esquema: bool = False) -> str:
    """Crea el trabajo en el ledger (para devolver su id de inmediato) y lo corre en un hilo."""
    from .harness_migracion import orden_de_migracion
    from .orquestador import migrar_todo

    if ocupado():
        raise TrabajoEnCurso("Ya hay una migración o comparación en curso; espera a que termine.")
    job_id = ledger.iniciar_trabajo(fuente, "firebird" if usar_firebird_real else "fixture", len(orden_de_migracion(fuente)))
    try:
        _en_hilo(
            job_id,
            lambda: migrar_todo(
                fuente,
                usar_firebird_real=usar_firebird_real,
                permitir_borrador=permitir_borrador,
                reset_esquema=reset_esquema,
                job_id=job_id,
            ),
        )
    except TrabajoEnCurso:
        ledger.finalizar_trabajo(job_id, estado="error", detalle={"error": "Otro trabajo empezó al mismo tiempo."})
        raise
    return job_id


def iniciar_comparacion(fuente: str, *, usar_firebird_real: bool) -> str:
    """Registra la comparación en el ledger (visible de inmediato como 'en
    curso') y la corre en un hilo."""
    from .diferencial import comparar_fuente

    if ocupado():
        raise TrabajoEnCurso("Ya hay una migración o comparación en curso; espera a que termine.")
    comparacion_id = ledger.iniciar_comparacion(fuente, "firebird" if usar_firebird_real else "fixture")
    try:
        _en_hilo(
            comparacion_id, lambda: comparar_fuente(fuente, usar_firebird_real=usar_firebird_real, comparacion_id=comparacion_id)
        )
    except TrabajoEnCurso:
        ledger.finalizar_comparacion(comparacion_id, estado="error", detalle={"error": "Otro trabajo empezó al mismo tiempo."})
        raise
    return comparacion_id


def iniciar_pruebas(suites: list[str]) -> threading.Thread:
    """Corre las suites una tras otra en un hilo. No toman el candado de
    migración: no escriben en el esquema 'config' (usan 'prueba' y datos
    temporales); entre ellas se serializan con el candado de pruebas.ejecutar_suite."""
    from .pruebas import ejecutar_suite

    ids = [ledger.iniciar_prueba(s) for s in suites]  # visibles como 'Running' de inmediato

    def ejecutar():
        for suite, prueba_id in zip(suites, ids, strict=True):
            try:
                ejecutar_suite(suite, prueba_id=prueba_id)
            except Exception as exc:
                ledger.finalizar_prueba(prueba_id, estado="error", detalle={"error": f"{type(exc).__name__}: {exc}"})

    hilo = threading.Thread(target=ejecutar, name="pruebas", daemon=True)
    _hilos["pruebas"] = hilo
    hilo.start()
    return hilo


def esperar(nombre: str, timeout: float | None = None) -> None:
    hilo = _hilos.get(nombre)
    if hilo:
        hilo.join(timeout)
