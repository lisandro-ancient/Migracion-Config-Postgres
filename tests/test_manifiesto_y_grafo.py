import allure
import pytest
from pydantic import ValidationError

from config_microsip.grafo import ErrorDeGrafo, describir_grafo, orden_de_extraccion
from config_microsip.manifiesto import Manifiesto, listar_fuentes, listar_manifiestos
from config_microsip.reglas.motor import normalizar_fila
from config_microsip.reglas.primitivas import ErrorDeTransformacion

pytestmark = allure.feature("Manifiesto, grafo y motor")

BASE = {
    "fuente": "x",
    "tabla_origen": "T",
    "tabla_destino": "t",
    "llave_primaria": "id",
    "fixture": "f.json",
    "campos": [{"origen": "ID", "destino": "id", "regla": "entero"}],
}


def test_listado_de_fuentes_y_manifiestos(datos):
    assert listar_fuentes() == ["prueba"]
    assert listar_manifiestos("prueba") == ["elementos", "grupos"]


def test_manifiesto_carga(manifiesto):
    assert manifiesto.estado == "vigente"
    assert manifiesto.llaves == ["elemento_id"]
    assert manifiesto.catalogo("grupos").tabla_origen == "GRUPOS"


@pytest.mark.parametrize(
    "cambio,mensaje",
    [
        ({"llave_primaria": "otra"}, "llave_primaria"),
        ({"campos": [{"origen": "ID", "destino": "id", "regla": "inventada"}]}, "regla desconocida"),
        ({"campos": [{"origen": "ID", "destino": "id", "regla": "entero", "catalogo_fk": "nope"}]}, "no está declarado"),
        ({"depende_de": ["nope"]}, "depende_de"),
        ({"campo_checksum": "nope"}, "campo_checksum"),
        ({"catalogos": [{"nombre": "c", "tipo": "tabla", "columnas": ["id"]}]}, "tabla_origen"),
    ],
)
def test_manifiesto_rechaza_referencias_invalidas(cambio, mensaje):
    with pytest.raises(ValidationError, match=mensaje):
        Manifiesto.model_validate({**BASE, **cambio})


def test_llave_compuesta():
    m = Manifiesto.model_validate(
        {
            **BASE,
            "llave_primaria": ["id", "sub"],
            "campos": [
                {"origen": "ID", "destino": "id", "regla": "entero"},
                {"origen": "SUB", "destino": "sub", "regla": "texto"},
            ],
        }
    )
    assert m.nombre_llave == "id+sub"
    assert m.valor_llave({"id": 1, "sub": "A"}) == "1|A"
    assert m.valor_llave_crudo({"ID": 1, "SUB": "A  "}) == "1|A"


def test_grafo_orden_de_extraccion(manifiesto):
    orden = orden_de_extraccion(manifiesto)
    assert orden[-1] == "elementos"
    assert set(orden[:-1]) == {"estatus_elemento", "grupos"}
    assert {"desde": "elementos", "hacia": "grupos"} in describir_grafo(manifiesto)["aristas"]


def test_grafo_detecta_ciclo(manifiesto):
    manifiesto.catalogos[0].nombre = "elementos"  # la tabla dependería de sí misma
    manifiesto.depende_de = ["elementos"]
    with pytest.raises(ErrorDeGrafo):
        orden_de_extraccion(manifiesto)


def test_motor_nulo_permitido_no_invoca_la_regla(manifiesto):
    fila = {
        "ELEMENTO_ID": 9,
        "NOMBRE": "n",
        "ACTIVO": "S",
        "ESTATUS": "A",
        "GRUPO_ID": None,
        "IMPORTE": "1",
        "FECHA_ALTA": "2020-01-01 00:00:00",
        "NOTAS": None,
    }
    resultado = normalizar_fila(manifiesto, fila)
    assert resultado["grupo_id"] is None and resultado["notas"] is None


def test_motor_rechazo_identifica_llave_y_campo(manifiesto):
    fila = {
        "ELEMENTO_ID": 9,
        "NOMBRE": "n",
        "ACTIVO": "X",
        "ESTATUS": "A",
        "GRUPO_ID": None,
        "IMPORTE": "1",
        "FECHA_ALTA": "2020-01-01 00:00:00",
        "NOTAS": None,
    }
    with pytest.raises(ErrorDeTransformacion, match=r"elemento_id=9: Bandera 'activo'"):
        normalizar_fila(manifiesto, fila)
