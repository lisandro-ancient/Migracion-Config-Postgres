"""Ejecutor de suites que usa el panel: corre pytest de verdad en un
subproceso y cuenta resultados desde el reporte JUnit."""

import textwrap

import allure
import pytest

from config_microsip import ledger
from config_microsip.pruebas import SUITES, ejecutar_suite, leer_junit

pytestmark = allure.feature("Ejecutor de pruebas del panel")


def test_leer_junit(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        textwrap.dedent("""\
        <testsuites><testsuite tests="4" failures="1" errors="0" skipped="1">
          <testcase classname="m" name="a" time="0.1"/>
          <testcase classname="m" name="b" time="0.2"><failure message="boom"/></testcase>
          <testcase classname="m" name="c" time="0"><skipped message="sin db"/></testcase>
          <testcase classname="m" name="d" time="0.3"/>
        </testsuite></testsuites>""")
    )
    r = leer_junit(xml)
    assert (r["total"], r["pasaron"], r["fallaron"], r["saltadas"]) == (4, 2, 1, 1)
    assert {c["nombre"]: c["resultado"] for c in r["casos"]} == {
        "m::a": "passed",
        "m::b": "failed",
        "m::c": "skipped",
        "m::d": "passed",
    }
    assert r["casos"][1]["mensaje"] == "boom"


def test_ejecutar_suite_real_y_registrar(datos, tmp_path):
    carpeta = tmp_path / "suite_demo"
    carpeta.mkdir()
    (carpeta / "test_demo.py").write_text("def test_ok():\n    assert True\n\ndef test_falla():\n    assert 1 == 2\n")
    resultado = ejecutar_suite("all", directorio=carpeta)
    assert (resultado["estado"], resultado["pasaron"], resultado["fallaron"]) == ("fail", 1, 1)
    registro = ledger.listar_pruebas(limite=1)[0]
    assert registro["suite"] == "all" and registro["estado"] == "fail" and registro["pasaron"] == 1


def test_suite_desconocida():
    with pytest.raises(ValueError):
        ejecutar_suite("nope")


def test_cada_modulo_tiene_suite():
    """Todo tests/test_*.py está clasificado (si no, la recolección falla)."""
    from pathlib import Path

    from conftest import SUITE_POR_MODULO

    modulos = {p.stem for p in Path(__file__).parent.glob("test_*.py")}
    assert modulos <= set(SUITE_POR_MODULO), modulos - set(SUITE_POR_MODULO)
    assert set(SUITE_POR_MODULO.values()) == set(SUITES)
