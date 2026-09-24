"""Pruebas contra una base Firebird real. Se SALTAN (no fallan) si no hay
FIREBIRD_DATABASE configurada o la conexión no abre — para que nunca aparezca
un "passed" por falta de entorno. Con tu CONFIG.FDB en .env, corren solas."""

import allure
import pytest

from config_microsip.conexion import verificar_conexion

pytestmark = allure.feature("Firebird real (solo lectura)")


@pytest.fixture(scope="module")
def conexion():
    resultado = verificar_conexion()
    if not resultado.get("ok"):
        pytest.skip(f"Sin base Firebird disponible: {resultado.get('error')}")
    return resultado


def test_transaccion_es_de_solo_lectura(conexion):
    assert conexion["transaccion_solo_lectura"] is True


def test_diagnostico_de_base_config_es_coherente(conexion):
    ejes, cascadas = conexion["tablas_eje"], conexion["fk_en_cascada_hacia"]
    assert conexion["es_base_config"] == (all(ejes.values()) and all(cascadas.values()))
    assert (conexion["motivo"] is None) == conexion["es_base_config"]


def test_escritura_rechazada_por_el_servidor(conexion):
    from config_microsip.conexion import conexion_solo_lectura

    with conexion_solo_lectura() as cur, pytest.raises(Exception, match=r"(?i)read-only|metadata update"):
        cur.ejecutar("CREATE TABLE ZZ_PRUEBA_SOLO_LECTURA (I INTEGER)")


def test_esquema_se_puede_listar_y_describir(conexion):
    from config_microsip.esquema import describir_tabla, listar_tablas

    tablas = listar_tablas()
    assert len(tablas) == conexion["tablas_de_usuario"] > 0
    descripcion = describir_tabla(tablas[0]["tabla"])
    assert descripcion["columnas"] and descripcion["filas"] is not None
