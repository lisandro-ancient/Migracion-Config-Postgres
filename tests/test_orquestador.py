import json

import allure
import pytest

from config_microsip import ledger
from config_microsip.extract import FixtureInexistente
from config_microsip.orquestador import extraer_y_validar

pytestmark = allure.feature("Orquestador y evidencia")


def test_ciclo_completo_escribe_evidencia_y_ledger(datos):
    reporte = extraer_y_validar("prueba", "elementos")
    assert reporte["ok_general"] is True and reporte["modo"] == "fixture"
    run_dir = datos / "runs" / "prueba" / "elementos" / reporte["run_id"]
    for archivo in (
        "comparison.json",
        "report.md",
        "queries.json",
        "entrada_muestra.json",
        "evidence/elementos_candidato.csv",
        "evidence/elementos_rechazadas.csv",
    ):
        assert (run_dir / archivo).exists(), archivo
    comparison = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["filas_rechazadas_en_transformacion"][0]["llave"] == "4"
    assert "Dólar ñandú" in (run_dir / "evidence/elementos_candidato.csv").read_text(encoding="utf-8")
    corrida = ledger.obtener_corrida(reporte["run_id"])
    assert (corrida["estado"], corrida["filas_entrada"], corrida["filas_salida"], corrida["filas_falla"]) == ("ok", 6, 5, 1)


def test_error_queda_registrado_en_ledger(datos):
    (datos / "fixtures/prueba/elementos_raw_snapshot.json").unlink()
    with pytest.raises(FixtureInexistente):
        extraer_y_validar("prueba", "elementos")
    assert ledger.listar_corridas(fuente="prueba", tabla="elementos")[0]["estado"] == "error"
