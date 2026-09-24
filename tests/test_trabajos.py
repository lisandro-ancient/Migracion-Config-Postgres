"""Trabajos en segundo plano y registro en el ledger (lo que alimenta el panel)."""

import allure
import pytest

from config_microsip import ledger, trabajos

pytestmark = allure.feature("Trabajos y ledger")


def test_ciclo_de_vida_de_un_trabajo_en_el_ledger(datos):
    job = ledger.iniciar_trabajo("prueba", "fixture", 3)
    ledger.actualizar_trabajo(job, tabla_actual="grupos", paso_actual="cargando", tablas_ok=1)
    t = ledger.obtener_trabajo(job)
    assert (t["estado"], t["tabla_actual"], t["paso_actual"], t["tablas_ok"]) == ("en_progreso", "grupos", "cargando", 1)
    ledger.finalizar_trabajo(job, estado="ok", tablas_ok=3)
    t = ledger.obtener_trabajo(job)
    assert t["estado"] == "ok" and t["terminado_en"] and t["paso_actual"] is None
    assert ledger.listar_trabajos()[0]["job_id"] == job


def test_trabajos_interrumpidos_se_marcan_al_arrancar(datos):
    job = ledger.iniciar_trabajo("prueba", "fixture", 1)
    prueba = ledger.iniciar_prueba("unit")
    assert ledger.marcar_trabajos_interrumpidos() >= 2
    assert ledger.obtener_trabajo(job)["estado"] == "error"
    assert ledger.listar_pruebas(limite=1)[0]["estado"] == "error"
    assert prueba


def test_ledger_viejo_se_actualiza_sin_perder_historial(datos):
    import sqlite3

    from config_microsip.rutas import ruta_ledger

    ruta = ruta_ledger()
    conn = sqlite3.connect(ruta)
    conn.execute(
        "CREATE TABLE corridas (run_id TEXT PRIMARY KEY, fuente TEXT NOT NULL, tabla TEXT NOT NULL, modo TEXT NOT NULL, "
        "estado TEXT NOT NULL DEFAULT 'en_progreso', iniciado_en REAL NOT NULL, terminado_en REAL, filas_entrada INTEGER, "
        "filas_salida INTEGER, filas_falla INTEGER, detalle_json TEXT)"
    )
    conn.execute(
        "INSERT INTO corridas (run_id, fuente, tabla, modo, estado, iniciado_en) VALUES ('viejo', 'prueba', 'x', 'fixture', 'ok', 1)"
    )
    conn.commit()
    conn.close()
    c = ledger.obtener_corrida("viejo")
    assert c["tipo"] == "validacion" and c["job_id"] is None


def test_actividad_reciente_mezcla_todo(datos):
    ledger.finalizar_corrida(ledger.iniciar_corrida("prueba", "t", "fixture"), estado="ok")
    ledger.finalizar_comparacion(ledger.iniciar_comparacion("prueba", "fixture"), estado="ok", coinciden=3)
    ledger.finalizar_prueba(ledger.iniciar_prueba("unit"), estado="ok", pasaron=2, fallaron=0)
    tipos = {e["tipo"] for e in ledger.actividad_reciente()}
    assert {"validacion", "comparacion", "prueba"} <= tipos


def test_migracion_en_segundo_plano_con_progreso(pg):
    job_id = trabajos.iniciar_migracion("prueba", usar_firebird_real=False, permitir_borrador=False)
    with pytest.raises(trabajos.TrabajoEnCurso):
        trabajos.iniciar_migracion("prueba", usar_firebird_real=False, permitir_borrador=False)
    trabajos.esperar(job_id, timeout=60)
    t = ledger.obtener_trabajo(job_id)
    assert t["estado"] == "ok", t
    assert (t["tablas_ok"], t["tablas_total"], t["filas_origen"], t["filas_migradas"]) == (2, 2, 8, 7)
    assert t["comparacion_id"] and not trabajos.ocupado()
    assert [c["tabla"] for c in sorted(ledger.listar_corridas(job_id=job_id), key=lambda c: c["iniciado_en"])] == [
        "grupos",
        "elementos",
    ]


def test_error_en_trabajo_queda_registrado(pg, datos):
    (datos / "fixtures/prueba/grupos_raw_snapshot.json").unlink()
    job_id = trabajos.iniciar_migracion("prueba", usar_firebird_real=False, permitir_borrador=False)
    trabajos.esperar(job_id, timeout=60)
    t = ledger.obtener_trabajo(job_id)
    assert t["estado"] == "fail" and t["tablas_fail"] == 2  # grupos sin snapshot; elementos sin su tabla padre
    assert not trabajos.ocupado()
