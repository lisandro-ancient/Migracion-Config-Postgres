"""Suites de pruebas ejecutables desde el panel o el MCP.

Cada módulo de tests/ pertenece a exactamente una suite (ver
``tests/conftest.py::SUITE_POR_MODULO``), marcada con el marcador de pytest del
mismo nombre. Ejecutar una suite = ``pytest -m <suite>`` en un subproceso, con
reporte JUnit para contar resultados sin parsear la salida de la terminal.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import ledger
from .rutas import RUTA_PROYECTO

SUITES = {
    "unit": "Pruebas unitarias",
    "integration": "Pruebas de integración",
    "differential": "Pruebas diferenciales",
    "e2e": "Pruebas de extremo a extremo",
}
TIEMPO_LIMITE = 600
# Las suites de integración, diferencial y e2e reinician el esquema 'prueba' de
# PostgreSQL: dos corridas simultáneas se pisarían. Una a la vez por proceso.
_candado = threading.Lock()


def leer_junit(ruta: Path) -> dict[str, Any]:
    raiz = ET.parse(ruta).getroot()  # noqa: S314 — XML que acaba de generar nuestro propio pytest, no entrada externa
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    fallaron = sum(int(s.get("failures", 0)) for s in suites)
    errores = sum(int(s.get("errors", 0)) for s in suites)
    saltadas = sum(int(s.get("skipped", 0)) for s in suites)
    casos = []
    for caso in raiz.iter("testcase"):
        resultado = "passed"
        mensaje = None
        for etiqueta in ("failure", "error", "skipped"):
            nodo = caso.find(etiqueta)
            if nodo is not None:
                resultado = {"failure": "failed", "error": "error", "skipped": "skipped"}[etiqueta]
                mensaje = (nodo.get("message") or "")[:300]
        casos.append(
            {
                "nombre": f"{caso.get('classname')}::{caso.get('name')}",
                "resultado": resultado,
                "segundos": float(caso.get("time", 0)),
                "mensaje": mensaje,
            }
        )
    return {
        "total": total,
        "pasaron": total - fallaron - errores - saltadas,
        "fallaron": fallaron,
        "errores": errores,
        "saltadas": saltadas,
        "casos": casos,
    }


def ejecutar_suite(suite: str, *, directorio: Path | None = None, prueba_id: str | None = None) -> dict[str, Any]:
    """Corre una suite (o ``all``) y registra el resultado en el ledger."""
    if suite != "all" and suite not in SUITES:
        raise ValueError(f"Suite desconocida: {suite!r} (válidas: {', '.join(SUITES)}, all)")
    prueba_id = prueba_id or ledger.iniciar_prueba(suite)
    with _candado, tempfile.TemporaryDirectory() as tmp:
        ledger._actualizar("pruebas", "prueba_id", prueba_id, {"iniciado_en": time.time()})  # la espera en cola no cuenta
        junit = Path(tmp) / "junit.xml"
        comando = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", f"--junitxml={junit}"]
        if suite != "all":
            comando += ["-m", suite]
        if directorio:
            comando.append(str(directorio))
        entorno = {**os.environ, "SKIP_ALLURE_REPORT": "1"}
        try:
            proceso = subprocess.run(
                comando, cwd=RUTA_PROYECTO, capture_output=True, text=True, timeout=TIEMPO_LIMITE, env=entorno
            )
        except subprocess.TimeoutExpired:
            ledger.finalizar_prueba(prueba_id, estado="error", detalle={"error": f"Superó {TIEMPO_LIMITE}s"})
            return {"prueba_id": prueba_id, "suite": suite, "estado": "error"}
        if not junit.exists():
            salida = (proceso.stdout + proceso.stderr)[-2000:]
            ledger.finalizar_prueba(prueba_id, estado="error", detalle={"error": "pytest no produjo reporte", "salida": salida})
            return {"prueba_id": prueba_id, "suite": suite, "estado": "error", "salida": salida}
        conteo = leer_junit(junit)
    estado = "ok" if conteo["fallaron"] == 0 and conteo["errores"] == 0 and conteo["total"] > 0 else "fail"
    if conteo["total"] == 0:
        estado = "error"
    ledger.finalizar_prueba(
        prueba_id,
        estado=estado,
        pasaron=conteo["pasaron"],
        fallaron=conteo["fallaron"],
        saltadas=conteo["saltadas"],
        errores=conteo["errores"],
        detalle={"casos": conteo["casos"], "codigo_salida": proceso.returncode},
    )
    return {"prueba_id": prueba_id, "suite": suite, "estado": estado, **{k: v for k, v in conteo.items() if k != "casos"}}


def ultimo_resultado_por_suite() -> dict[str, dict[str, Any] | None]:
    resultado = {}
    for suite in SUITES:
        corridas = ledger.listar_pruebas(limite=1, suite=suite)
        resultado[suite] = corridas[0] if corridas else None
    return resultado
