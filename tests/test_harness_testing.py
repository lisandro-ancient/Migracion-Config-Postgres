import copy

import allure

from config_microsip.harness_extraccion import construir_candidato
from config_microsip.harness_testing import ejecutar_todas_las_validaciones
from config_microsip.orquestador import cargar_golden

pytestmark = allure.feature("Harness de Testing")


def _por_nombre(reporte):
    return {v["verificacion"]: v for v in reporte.verificaciones}


def test_datos_sinteticos_pasan_con_un_rechazo_explicito(manifiesto):
    resultado = construir_candidato(manifiesto)
    reporte = ejecutar_todas_las_validaciones(manifiesto, resultado, cargar_golden("prueba", "elementos"))
    assert reporte.ok_general, reporte.verificaciones
    assert (reporte.filas_extraidas, reporte.filas_aceptadas, reporte.filas_rechazadas) == (6, 5, 1)
    assert resultado.rechazadas[0]["llave"] == "4"
    assert "golden_dataset" in _por_nombre(reporte)
    assert _por_nombre(reporte)["checksum_importe"]["suma_candidato"] == "86.4750"


def test_detecta_snapshot_truncado(manifiesto):
    resultado = construir_candidato(manifiesto)
    resultado.conteo_origen = 7
    reporte = ejecutar_todas_las_validaciones(manifiesto, resultado)
    assert not _por_nombre(reporte)["conteo_filas"]["ok"]


def test_detecta_llave_duplicada(manifiesto):
    resultado = construir_candidato(manifiesto)
    resultado.candidato.append(copy.deepcopy(resultado.candidato[0]))
    assert _por_nombre(ejecutar_todas_las_validaciones(manifiesto, resultado))["llave_primaria_unica"]["duplicadas"] == ["1"]


def test_detecta_fk_sin_catalogo(manifiesto):
    resultado = construir_candidato(manifiesto)
    resultado.candidato[0]["grupo_id"] = 999
    v = _por_nombre(ejecutar_todas_las_validaciones(manifiesto, resultado))["integridad_referencial"]
    assert not v["ok"] and v["resultados"]["grupo_id"]["valores_sin_catalogo"] == ["999"]


def test_detecta_diferencia_contra_golden(manifiesto):
    resultado = construir_candidato(manifiesto)
    resultado.candidato[1]["importe"] = resultado.candidato[1]["importe"].quantize(1)  # redondeo indebido
    v = _por_nombre(ejecutar_todas_las_validaciones(manifiesto, resultado, cargar_golden("prueba", "elementos")))
    assert not v["golden_dataset"]["ok"]
    assert any("importe" in d for d in v["golden_dataset"]["diferencias"])
    assert not v["checksum_importe"]["ok"]
