"""Orquestador: encadena Harness de Extracción -> Harness de Testing y
registra la corrida en el ledger. Es la única secuencia que usan la CLI, el
servidor MCP y el dashboard, para no duplicarla en tres lugares.

Cuando el resultado es FAIL, el paso siguiente no es código: quien invoca
(una persona, o un agente vía MCP) lee comparison.json/report.md y corrige el
manifiesto o el golden.
"""

from __future__ import annotations

import json
from typing import Any

from . import ledger
from .harness_extraccion import construir_candidato, describir_queries
from .harness_testing import ejecutar_todas_las_validaciones, generar_evidencia
from .manifiesto import cargar_manifiesto, ruta_golden
from .rutas import ruta_runs

MUESTRA_ENTRADA_TAMANO = 8


def cargar_golden(fuente: str, tabla: str) -> list[dict[str, Any]] | None:
    """``{"_nota": "cómo se verificó", "casos": [{"entrada": ..., "salida_esperada": ...}]}``"""
    ruta = ruta_golden(fuente, tabla)
    return json.loads(ruta.read_text(encoding="utf-8"))["casos"] if ruta.exists() else None


def extraer_y_validar(fuente: str, tabla: str, *, usar_firebird_real: bool = False) -> dict[str, Any]:
    manifiesto = cargar_manifiesto(fuente, tabla)
    modo = "firebird" if usar_firebird_real else "fixture"
    run_id = ledger.iniciar_corrida(fuente, tabla, modo)
    try:
        resultado = construir_candidato(manifiesto, usar_firebird_real=usar_firebird_real)
        reporte = ejecutar_todas_las_validaciones(manifiesto, resultado, cargar_golden(fuente, tabla))
        run_dir = ruta_runs() / fuente / tabla / run_id
        comparison = generar_evidencia(run_dir, manifiesto, reporte, resultado)
        (run_dir / "queries.json").write_text(
            json.dumps(describir_queries(manifiesto), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (run_dir / "entrada_muestra.json").write_text(
            json.dumps(resultado.filas_crudas[:MUESTRA_ENTRADA_TAMANO], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        ledger.finalizar_corrida(run_id, estado="error", detalle={"error": f"{type(exc).__name__}: {exc}"})
        raise
    ledger.finalizar_corrida(
        run_id,
        estado="ok" if reporte.ok_general else "fail",
        filas_entrada=reporte.filas_extraidas,
        filas_salida=reporte.filas_aceptadas,
        filas_falla=reporte.filas_rechazadas,
    )
    comparison.update({"run_id": run_id, "run_dir": str(run_dir), "estado_manifiesto": manifiesto.estado})
    return comparison


class ManifiestoEnBorrador(RuntimeError):
    pass


def migrar_a_postgres(
    fuente: str,
    tabla: str,
    *,
    usar_firebird_real: bool = False,
    permitir_borrador: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Extraer -> validar contra el origen -> (solo si pasa) cargar a PostgreSQL
    -> verificar en PostgreSQL. Si la validación previa falla, no se carga nada:
    PostgreSQL nunca recibe un candidato que no cuadra con el origen."""
    from .config import ConfigPostgres
    from .harness_migracion import asegurar_tabla, cargar_espejo, conectar, validar_en_postgres

    manifiesto = cargar_manifiesto(fuente, tabla)
    if manifiesto.estado != "vigente" and not permitir_borrador:
        raise ManifiestoEnBorrador(
            f"El manifiesto {fuente}.{tabla} está en estado '{manifiesto.estado}'. Revísalo y pásalo a 'vigente', "
            "o usa --permitir-borrador para migrarlo de todos modos."
        )
    modo = "firebird" if usar_firebird_real else "fixture"
    run_id = ledger.iniciar_corrida(fuente, tabla, modo, tipo="migracion", job_id=job_id)
    run_dir = ruta_runs() / fuente / tabla / run_id

    def paso(nombre: str) -> None:
        if job_id:
            ledger.actualizar_trabajo(job_id, tabla_actual=tabla, paso_actual=nombre)

    try:
        paso("extrayendo")
        resultado = construir_candidato(manifiesto, usar_firebird_real=usar_firebird_real)
        paso("validando")
        reporte = ejecutar_todas_las_validaciones(manifiesto, resultado, cargar_golden(fuente, tabla))
        carga: dict[str, Any] = {"cargado": False}
        ddl = None
        if reporte.ok_general:
            config_pg = ConfigPostgres.desde_entorno()
            with conectar(config_pg) as conn:
                paso("cargando")
                ddl = asegurar_tabla(conn, manifiesto)
                carga = {
                    "cargado": True,
                    "destino": f"{config_pg.base_datos}.{fuente}.{manifiesto.tabla_destino}",
                    **cargar_espejo(conn, manifiesto, resultado.candidato),
                }
                paso("verificando")
                reporte.verificaciones += validar_en_postgres(conn, manifiesto, resultado.candidato)
            reporte.ok_general = all(v["ok"] for v in reporte.verificaciones)
        else:
            carga["motivo"] = "La validación contra el origen falló; no se cargó nada en PostgreSQL."
        comparison = generar_evidencia(run_dir, manifiesto, reporte, resultado)
        comparison["migracion_postgres"] = carga
        (run_dir / "comparison.json").write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        queries = describir_queries(manifiesto)
        queries["ddl_postgres"] = ddl
        (run_dir / "queries.json").write_text(json.dumps(queries, indent=2, ensure_ascii=False), encoding="utf-8")
        (run_dir / "entrada_muestra.json").write_text(
            json.dumps(resultado.filas_crudas[:MUESTRA_ENTRADA_TAMANO], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        ledger.finalizar_corrida(run_id, estado="error", detalle={"error": f"{type(exc).__name__}: {exc}"})
        raise
    ledger.finalizar_corrida(
        run_id,
        estado="ok" if reporte.ok_general else "fail",
        filas_entrada=reporte.filas_extraidas,
        filas_salida=reporte.filas_aceptadas if carga["cargado"] else 0,
        filas_falla=reporte.filas_rechazadas,
    )
    comparison.update({"run_id": run_id, "run_dir": str(run_dir), "estado_manifiesto": manifiesto.estado})
    return comparison


def migrar_todo(
    fuente: str,
    *,
    usar_firebird_real: bool = False,
    permitir_borrador: bool = False,
    reset_esquema: bool = False,
    job_id: str | None = None,
    con_diferencial: bool = True,
) -> dict[str, Any]:
    """Un trabajo de migración: todas las tablas de la fuente en orden
    padre -> hijo y, al final, una comparación diferencial Firebird ↔ PostgreSQL.
    Sigue con las demás tablas aunque una falle, y reporta cada una. El
    progreso queda en el ledger (``trabajos``) para que el panel lo muestre en vivo."""
    from .harness_migracion import conectar, orden_de_migracion, reiniciar_esquema

    modo = "firebird" if usar_firebird_real else "fixture"
    orden = orden_de_migracion(fuente)
    job_id = job_id or ledger.iniciar_trabajo(fuente, modo, len(orden))
    ledger.actualizar_trabajo(job_id, tablas_total=len(orden))
    tablas: list[dict[str, Any]] = []
    try:
        if reset_esquema:
            ledger.actualizar_trabajo(job_id, paso_actual="reiniciando esquema")
            with conectar() as conn:
                reiniciar_esquema(conn, fuente)
        for tabla in orden:
            try:
                r = migrar_a_postgres(
                    fuente, tabla, usar_firebird_real=usar_firebird_real, permitir_borrador=permitir_borrador, job_id=job_id
                )
                tablas.append(
                    {
                        "tabla": tabla,
                        "ok": r["ok_general"],
                        "run_id": r["run_id"],
                        "filas_origen": r["filas_extraidas"],
                        "filas": r["filas_aceptadas"] if r["migracion_postgres"]["cargado"] else 0,
                        "cargado": r["migracion_postgres"]["cargado"],
                        "fallas": [v["verificacion"] for v in r["verificaciones"] if not v["ok"]],
                    }
                )
            except Exception as exc:
                tablas.append(
                    {"tabla": tabla, "ok": False, "filas_origen": 0, "filas": 0, "error": f"{type(exc).__name__}: {exc}"}
                )
            ledger.actualizar_trabajo(
                job_id,
                tablas_ok=sum(t["ok"] for t in tablas),
                tablas_fail=sum(not t["ok"] for t in tablas),
                filas_origen=sum(t["filas_origen"] for t in tablas),
                filas_migradas=sum(t["filas"] for t in tablas),
            )
        diferencial = None
        if con_diferencial:
            from .diferencial import comparar_fuente

            ledger.actualizar_trabajo(job_id, tabla_actual=None, paso_actual="comparación diferencial")
            diferencial = comparar_fuente(fuente, usar_firebird_real=usar_firebird_real)
    except Exception as exc:
        ledger.finalizar_trabajo(job_id, estado="error", detalle={"error": f"{type(exc).__name__}: {exc}", "tablas": tablas})
        raise
    ok = all(t["ok"] for t in tablas) and (diferencial is None or diferencial["ok"])
    ledger.finalizar_trabajo(
        job_id,
        estado="ok" if ok else "fail",
        detalle={"tablas": tablas},
        comparacion_id=diferencial["comparacion_id"] if diferencial else None,
    )
    return {
        "job_id": job_id,
        "fuente": fuente,
        "orden": orden,
        "ok_general": ok,
        "tablas": tablas,
        "diferencial": {"ok": diferencial["ok"], "comparacion_id": diferencial["comparacion_id"], **diferencial["totales"]}
        if diferencial
        else None,
    }
