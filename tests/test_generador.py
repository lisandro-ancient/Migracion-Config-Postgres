import allure
import yaml

from config_microsip.esquema import nombre_tipo
from config_microsip.generador import generar_borrador
from config_microsip.manifiesto import Manifiesto

pytestmark = allure.feature("Generador de borradores")


def _col(nombre, categoria, *, nulo=False, longitud=None, pk=False):
    return {
        "nombre": nombre,
        "tipo": categoria.upper(),
        "categoria": categoria,
        "longitud": longitud,
        "nulo_permitido": nulo,
        "posicion": 0,
        "charset": None,
        "es_llave_primaria": pk,
    }


DESCRIPCION = {
    "tabla": "TABLA_X",
    "filas": 3,
    "llave_primaria": ["ID"],
    "llaves_foraneas": [
        {
            "restriccion": "FK1",
            "columna": "GRUPO_ID",
            "tabla_referida": "GRUPOS",
            "columna_referida": "GRUPO_ID",
            "al_borrar": "cascade",
        }
    ],
    "columnas": [
        _col("ID", "entero", pk=True),
        _col("NOMBRE", "texto", longitud=50),
        _col("ACTIVO", "texto", longitud=1),
        _col("TIPO", "texto", longitud=1, nulo=True),
        _col("GRUPO_ID", "entero", nulo=True),
        _col("MONTO", "decimal"),
        _col("CREADO", "timestamp"),
        _col("FOTO", "blob"),
        _col("PASSWORD", "texto", longitud=70, nulo=True),
        _col("REFRESH_TOKEN", "blob_texto", nulo=True),
    ],
}


def test_borrador_es_un_manifiesto_valido_y_marcado_como_borrador():
    observados = {"ACTIVO": ["S", "N"], "TIPO": ["A", "B", None]}
    texto = generar_borrador(DESCRIPCION, fuente="config", valores_char1=observados.get)
    m = Manifiesto.model_validate(yaml.safe_load(texto))
    assert m.estado == "borrador" and m.llave_primaria == "id"
    reglas = {c.destino: c.regla for c in m.campos}
    assert reglas == {
        "id": "entero",
        "nombre": "texto",
        "activo": "bandera_sn",
        "tipo": "texto",
        "grupo_id": "entero",
        "monto": "decimal_con_signo",
        "creado": "timestamp",
    }
    assert "FOTO (BLOB): excluida" in texto
    assert "FK real en origen: GRUPO_ID -> GRUPOS.GRUPO_ID" in texto
    assert m.depende_de == ["ref_grupos"]
    assert m.catalogo("ref_grupos").tabla_origen == "GRUPOS"
    assert m.catalogo("ref_grupos").al_borrar == "cascade"
    assert next(c for c in m.campos if c.destino == "grupo_id").catalogo_fk == "ref_grupos"
    assert "PASSWORD: excluida — contiene credenciales" in texto
    assert "REFRESH_TOKEN: excluida" in texto
    assert "¿catálogo derivado?" in texto


def test_llave_compuesta_en_borrador():
    d = {**DESCRIPCION, "llave_primaria": ["ID", "NOMBRE"]}
    m = Manifiesto.model_validate(yaml.safe_load(generar_borrador(d, fuente="config")))
    assert m.llaves == ["id", "nombre"]


def test_nombre_tipo_numeric():
    assert nombre_tipo(8, 1, 9, -2) == "NUMERIC(9,2)"
    assert nombre_tipo(16, 2, 18, -4) == "DECIMAL(18,4)"
    assert nombre_tipo(37, 0, None, 0) == "VARCHAR"


def test_fk_autorreferente_no_genera_ciclo():
    from config_microsip.grafo import orden_de_extraccion

    d = {
        "tabla": "USUARIOS",
        "filas": 0,
        "llave_primaria": ["USUARIO_ID"],
        "llaves_foraneas": [
            {"restriccion": "FK_ROL", "columna": "ROL_ID", "tabla_referida": "USUARIOS", "columna_referida": "USUARIO_ID"}
        ],
        "columnas": [_col("USUARIO_ID", "entero", pk=True), _col("ROL_ID", "entero", nulo=True)],
    }
    m = Manifiesto.model_validate(yaml.safe_load(generar_borrador(d, fuente="config")))
    assert orden_de_extraccion(m) == ["ref_usuarios", "usuarios"]
