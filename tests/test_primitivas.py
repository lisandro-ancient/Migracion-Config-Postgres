from datetime import date, datetime, time
from decimal import Decimal

import allure
import pytest

from config_microsip.reglas import primitivas as p
from config_microsip.reglas.primitivas import ErrorDeTransformacion

pytestmark = allure.feature("Primitivas de normalización")


def test_texto_recorta_y_preserva_contenido():
    assert p.normalizar_texto("  Dólar, S.A.  ", campo="x", nulo_permitido=False) == "Dólar, S.A."


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_texto_obligatorio_rechaza_ausencia(valor):
    with pytest.raises(ErrorDeTransformacion):
        p.normalizar_texto(valor, campo="x", nulo_permitido=False)


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_texto_opcional_ausente_es_none(valor):
    assert p.normalizar_texto(valor, campo="x", nulo_permitido=True) is None


@pytest.mark.parametrize("valor,esperado", [("S", True), ("n", False), (" S ", True)])
def test_bandera_sn(valor, esperado):
    assert p.normalizar_bandera_sn(valor, campo="x") is esperado


@pytest.mark.parametrize("valor", [None, "X", "", "SI"])
def test_bandera_sn_sin_default(valor):
    with pytest.raises(ErrorDeTransformacion):
        p.normalizar_bandera_sn(valor, campo="x")


def test_booleano():
    assert p.normalizar_booleano(True, campo="x") is True
    assert p.normalizar_booleano(0, campo="x") is False
    with pytest.raises(ErrorDeTransformacion):
        p.normalizar_booleano("S", campo="x")


def test_catalogo_normaliza_y_valida_dominio():
    assert p.normalizar_codigo_catalogo(" a ", campo="x", dominio={"A": "Alta"}) == "A"
    with pytest.raises(ErrorDeTransformacion, match="fuera del dominio"):
        p.normalizar_codigo_catalogo("Z", campo="x", dominio={"A": "Alta"})


def test_decimal_conserva_precision_exacta():
    assert p.normalizar_decimal("0.123456", campo="x") == Decimal("0.123456")
    assert str(p.normalizar_decimal("100.50", campo="x")) == "100.50"


def test_decimal_minimo_y_con_signo():
    with pytest.raises(ErrorDeTransformacion, match="menor al mínimo"):
        p.normalizar_decimal("-1", campo="x")
    assert p.normalizar_decimal("-1.5", campo="x", minimo=None) == Decimal("-1.5")


@pytest.mark.parametrize("valor", ["abc", "NaN", "Infinity", None])
def test_decimal_invalido(valor):
    with pytest.raises(ErrorDeTransformacion):
        p.normalizar_decimal(valor, campo="x", minimo=None)


def test_entero():
    assert p.normalizar_entero("42", campo="x") == 42
    assert p.normalizar_entero(Decimal("7"), campo="x") == 7
    for invalido in ("4.5", "x", True, None):
        with pytest.raises(ErrorDeTransformacion):
            p.normalizar_entero(invalido, campo="x")


def test_fechas_y_horas():
    assert p.normalizar_fecha("2020-01-02", campo="x") == date(2020, 1, 2)
    assert p.normalizar_fecha(datetime(2020, 1, 2, 3, 4), campo="x") == date(2020, 1, 2)
    assert p.normalizar_timestamp("2020-01-02 03:04:05.123000", campo="x") == datetime(2020, 1, 2, 3, 4, 5, 123000)
    assert p.normalizar_hora("13:30:00", campo="x") == time(13, 30)
    with pytest.raises(ErrorDeTransformacion):
        p.normalizar_timestamp("ayer", campo="x")
