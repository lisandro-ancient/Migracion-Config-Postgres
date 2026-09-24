"""Pruebas diferenciales sobre la fuente sintética: tras migrar, origen y
PostgreSQL deben coincidir fila por fila; y el comparador debe detectar cada
tipo de desviación que se le introduce a propósito en PostgreSQL."""

import json
from datetime import datetime
from decimal import Decimal

import allure

from config_microsip import ledger
from config_microsip.diferencial import comparar_fuente, leer_informe
from config_microsip.orquestador import migrar_todo

pytestmark = allure.feature("Diferencial Firebird ↔ PostgreSQL")


def _tabla(informe, nombre):
    return next(t for t in informe["tablas"] if t["tabla"] == nombre)


def test_tras_migrar_todo_coincide(pg):
    resultado = migrar_todo("prueba", con_diferencial=False)
    assert resultado["ok_general"]
    informe = comparar_fuente("prueba")
    assert informe["ok"], informe
    elementos = _tabla(informe, "elementos")
    assert (elementos["coinciden"], elementos["diferentes"], elementos["faltantes"], elementos["sobrantes"]) == (5, 0, 0, 0)
    assert elementos["rechazadas"] == 1  # la fila 4 (ACTIVO='X') se espera ausente, no faltante
    assert elementos["esquema"]["ok"]
    assert informe["totales"]["coinciden"] == 7  # 5 elementos + 2 grupos
    registro = ledger.obtener_comparacion(informe["comparacion_id"])
    assert registro["estado"] == "ok" and registro["coinciden"] == 7
    assert leer_informe(informe["comparacion_id"])["totales"] == informe["totales"]


def test_trabajo_termina_con_comparacion_diferencial(pg):
    resultado = migrar_todo("prueba")
    assert resultado["diferencial"]["ok"] and resultado["diferencial"]["coinciden"] == 7
    trabajo = ledger.obtener_trabajo(resultado["job_id"])
    assert trabajo["estado"] == "ok" and trabajo["comparacion_id"] == resultado["diferencial"]["comparacion_id"]
    assert (trabajo["tablas_ok"], trabajo["tablas_total"], trabajo["filas_migradas"]) == (2, 2, 7)


def test_detecta_valor_distinto(pg):
    migrar_todo("prueba", con_diferencial=False)
    pg.execute('UPDATE "prueba"."elementos" SET importe = importe + 0.0001 WHERE elemento_id = 2')
    elementos = _tabla(comparar_fuente("prueba"), "elementos")
    assert not elementos["ok"] and elementos["diferentes"] == 1
    diferencia = elementos["muestra_diferencias"][0]
    assert diferencia["llave"] == "2" and list(diferencia["columnas"]) == ["importe"]
    assert diferencia["columnas"]["importe"]["origen"] == Decimal("-25.1250")


def test_detecta_texto_alterado_por_codificacion(pg):
    migrar_todo("prueba", con_diferencial=False)
    pg.execute("""UPDATE "prueba"."elementos" SET nombre = 'DÃ³lar Ã±andÃº' WHERE elemento_id = 5""")  # mojibake típico
    elementos = _tabla(comparar_fuente("prueba"), "elementos")
    assert elementos["diferentes"] == 1 and "nombre" in elementos["muestra_diferencias"][0]["columnas"]


def test_detecta_fila_faltante_y_sobrante(pg):
    migrar_todo("prueba", con_diferencial=False)
    pg.execute('DELETE FROM "prueba"."elementos" WHERE elemento_id = 6')
    pg.execute("""INSERT INTO "prueba"."elementos" VALUES (77, 'intrusa', true, 'A', 10, 1, '2020-01-01', NULL)""")
    elementos = _tabla(comparar_fuente("prueba"), "elementos")
    assert (elementos["faltantes"], elementos["sobrantes"]) == (1, 1)
    assert elementos["muestra_faltantes"] == ["6"] and elementos["muestra_sobrantes"] == ["77"]


def test_detecta_esquema_distinto(pg):
    migrar_todo("prueba", con_diferencial=False)
    pg.execute('ALTER TABLE "prueba"."elementos" DROP COLUMN notas')
    elementos = _tabla(comparar_fuente("prueba"), "elementos")
    assert not elementos["ok"] and not elementos["esquema"]["ok"]
    assert "notas" in elementos["esquema"]["esperadas"] and "notas" not in elementos["esquema"]["en_postgres"]


def test_tabla_no_migrada_cuenta_todo_como_faltante(pg):
    informe = comparar_fuente("prueba")
    grupos = _tabla(informe, "grupos")
    assert not informe["ok"] and grupos["tabla_en_postgres"] is False and grupos["faltantes"] == 2


def test_volver_a_migrar_repara_las_desviaciones(pg):
    migrar_todo("prueba", con_diferencial=False)
    pg.execute("""UPDATE "prueba"."grupos" SET nombre = 'cambiado' WHERE grupo_id = 20""")
    pg.execute("""INSERT INTO "prueba"."grupos" VALUES (99, 'sobra')""")
    assert not comparar_fuente("prueba")["ok"]
    assert migrar_todo("prueba")["diferencial"]["ok"]


def _esperado_independiente(fila):
    """Oráculo escrito aparte del motor de reglas, a partir de lo que declara
    el manifiesto sintético — si el motor tuviera un error, este no lo comparte."""

    def texto(v):
        return (v.strip() or None) if isinstance(v, str) else v

    return {
        "elemento_id": int(fila["ELEMENTO_ID"]),
        "nombre": texto(fila["NOMBRE"]),
        "activo": fila["ACTIVO"].strip().upper() == "S",
        "estatus": fila["ESTATUS"].strip().upper(),
        "grupo_id": fila["GRUPO_ID"],
        "importe": Decimal(fila["IMPORTE"]),
        "fecha_alta": datetime.fromisoformat(fila["FECHA_ALTA"]),
        "notas": texto(fila["NOTAS"]),
    }


def test_oraculo_independiente_contra_postgres(pg, datos):
    """Diferencial de extremo a extremo sin pasar por el motor: snapshot crudo
    -> expectativa independiente -> lo que quedó en PostgreSQL."""
    migrar_todo("prueba", con_diferencial=False)
    crudas = json.loads((datos / "fixtures/prueba/elementos_raw_snapshot.json").read_text(encoding="utf-8"))["filas"]
    validas = [f for f in crudas if f["ACTIVO"].strip().upper() in ("S", "N")]
    columnas = ["elemento_id", "nombre", "activo", "estatus", "grupo_id", "importe", "fecha_alta", "notas"]
    en_pg = {
        f[0]: dict(zip(columnas, f, strict=True))
        for f in pg.execute(f'SELECT {", ".join(columnas)} FROM "prueba"."elementos"').fetchall()
    }
    assert set(en_pg) == {int(f["ELEMENTO_ID"]) for f in validas}
    for fila in validas:
        esperado = _esperado_independiente(fila)
        assert en_pg[esperado["elemento_id"]] == esperado, f"elemento {esperado['elemento_id']}"
