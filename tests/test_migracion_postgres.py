"""Migración a PostgreSQL. Las pruebas de DDL/orden son puras; las de carga
necesitan el contenedor de docker-compose.yml y se SALTAN si no está arriba.
Usan el esquema 'prueba' (la fuente sintética), nunca 'config'."""

import json

import allure
import pytest

from config_microsip.harness_migracion import ddl_tabla, llaves_foraneas, orden_de_migracion
from config_microsip.manifiesto import cargar_manifiesto

pytestmark = allure.feature("Migración a PostgreSQL")


def test_ddl_replica_llaves_nulos_check_y_cascada(datos):
    ddl = ddl_tabla(cargar_manifiesto("prueba", "elementos"))
    assert 'CREATE TABLE IF NOT EXISTS "prueba"."elementos"' in ddl
    assert '"nombre" TEXT NOT NULL' in ddl and '"notas" TEXT,' in ddl
    assert '"importe" NUMERIC NOT NULL' in ddl
    assert 'PRIMARY KEY ("elemento_id")' in ddl
    assert "CHECK (\"estatus\" IN ('A', 'B'))" in ddl
    assert 'REFERENCES "prueba"."grupos" ("grupo_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED' in ddl


def test_orden_padre_antes_que_hijo(datos):
    assert orden_de_migracion("prueba") == ["grupos", "elementos"]
    assert llaves_foraneas(cargar_manifiesto("prueba", "elementos"))[0]["tabla_padre"] == "grupos"


def test_fk_sin_manifiesto_padre_se_omite(datos):
    (datos / "fuentes/prueba/manifiestos/grupos.yaml").unlink()
    ddl = ddl_tabla(cargar_manifiesto("prueba", "elementos"))
    assert "FOREIGN KEY" not in ddl and "FK omitida: grupo_id" in ddl


def test_borrador_no_se_migra_sin_permiso(datos):
    from config_microsip.orquestador import ManifiestoEnBorrador, migrar_a_postgres

    ruta = datos / "fuentes/prueba/manifiestos/grupos.yaml"
    ruta.write_text(ruta.read_text().replace("estado: vigente", "estado: borrador"))
    with pytest.raises(ManifiestoEnBorrador):
        migrar_a_postgres("prueba", "grupos")


def test_migrar_todo_carga_y_verifica_en_postgres(pg):
    from config_microsip.orquestador import migrar_todo

    resultado = migrar_todo("prueba")
    assert resultado["ok_general"], resultado
    assert [t["tabla"] for t in resultado["tablas"]] == ["grupos", "elementos"]
    assert pg.execute('SELECT count(*) FROM "prueba"."elementos"').fetchone()[0] == 5  # la fila 4 se rechazó
    assert pg.execute('SELECT nombre FROM "prueba"."elementos" WHERE elemento_id = 5').fetchone()[0] == "Dólar ñandú"
    assert str(pg.execute('SELECT importe FROM "prueba"."elementos" WHERE elemento_id = 2').fetchone()[0]) == "-25.1250"


def test_migracion_es_idempotente_y_espejo(pg, datos):
    from config_microsip.orquestador import migrar_a_postgres, migrar_todo

    migrar_todo("prueba")
    again = migrar_a_postgres("prueba", "elementos")
    assert again["migracion_postgres"]["filas_eliminadas"] == 0 and again["ok_general"]
    # El origen pierde una fila -> PostgreSQL la pierde también.
    ruta = datos / "fixtures/prueba/elementos_raw_snapshot.json"
    snap = json.loads(ruta.read_text(encoding="utf-8"))
    snap["filas"] = [f for f in snap["filas"] if f["ELEMENTO_ID"] != 6]
    snap["_meta"]["conteo_origen"] = len(snap["filas"])
    ruta.write_text(json.dumps(snap), encoding="utf-8")
    r = migrar_a_postgres("prueba", "elementos")
    assert r["ok_general"] and r["migracion_postgres"]["filas_eliminadas"] == 1
    assert pg.execute('SELECT count(*) FROM "prueba"."elementos" WHERE elemento_id = 6').fetchone()[0] == 0


def test_borrar_padre_cascada_como_en_origen(pg):
    from config_microsip.orquestador import migrar_todo

    migrar_todo("prueba")
    pg.execute('DELETE FROM "prueba"."grupos" WHERE grupo_id = 10')
    assert pg.execute('SELECT count(*) FROM "prueba"."elementos" WHERE grupo_id = 10').fetchone()[0] == 0


def test_validacion_fallida_no_carga_nada(pg, datos):
    from config_microsip.orquestador import migrar_a_postgres, migrar_todo

    migrar_todo("prueba")
    ruta = datos / "fixtures/prueba/elementos_raw_snapshot.json"
    snap = json.loads(ruta.read_text(encoding="utf-8"))
    snap["_meta"]["conteo_origen"] = 99  # snapshot "truncado"
    ruta.write_text(json.dumps(snap), encoding="utf-8")
    r = migrar_a_postgres("prueba", "elementos")
    assert not r["ok_general"] and r["migracion_postgres"]["cargado"] is False
    assert pg.execute('SELECT count(*) FROM "prueba"."elementos"').fetchone()[0] == 5  # intacto


def test_tabla_padre_faltante_da_error_claro(pg):
    from config_microsip.harness_migracion import ErrorDeMigracion
    from config_microsip.orquestador import migrar_a_postgres

    with pytest.raises(ErrorDeMigracion, match="Mígrala primero"):
        migrar_a_postgres("prueba", "elementos")


def test_esquema_de_version_anterior_se_detecta_con_mensaje_claro(pg, datos):
    """Evolución: si el manifiesto cambia (versión nueva del proyecto) y la tabla
    en PostgreSQL es la anterior, la migración se detiene y dice cómo recrearla."""
    from config_microsip.harness_migracion import ErrorDeMigracion
    from config_microsip.orquestador import migrar_a_postgres, migrar_todo

    migrar_todo("prueba")
    ruta = datos / "fuentes/prueba/manifiestos/grupos.yaml"
    ruta.write_text(
        ruta.read_text().replace("regla: texto}", "regla: texto}\n  - {origen: NOMBRE, destino: alias, regla: texto}")
    )
    with pytest.raises(ErrorDeMigracion, match=r"faltan alias.*--reset-esquema"):
        migrar_a_postgres("prueba", "grupos")
    assert migrar_todo("prueba", reset_esquema=True)["ok_general"]  # recrear lo resuelve


def test_tabla_migrada_queda_etiquetada_con_la_version(pg):
    from config_microsip import __version__
    from config_microsip.orquestador import migrar_todo

    migrar_todo("prueba")
    comentario = pg.execute('SELECT obj_description(\'"prueba"."grupos"\'::regclass)').fetchone()[0]
    assert comentario == f"prueba.GRUPOS — config-microsip {__version__}"
