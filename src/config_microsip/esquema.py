"""Introspección del esquema real de la base CONFIG, leyendo las tablas de
sistema de Firebird (``RDB$RELATIONS``, ``RDB$RELATION_FIELDS``,
``RDB$FIELDS``, restricciones). Es lo que permite trabajar sin suponer nada
sobre la estructura de CONFIG: los manifiestos se redactan a partir de lo que
este módulo reporta (ver generador.py), no de memoria.

Todas las consultas son de solo lectura y pasan por conexion_solo_lectura().
"""

from __future__ import annotations

from typing import Any

from .conexion import conexion_solo_lectura, identificador_seguro
from .config import ConfigFirebird

# RDB$FIELDS.RDB$FIELD_TYPE -> nombre SQL (Firebird 3/4/5).
_TIPOS = {
    7: "SMALLINT",
    8: "INTEGER",
    16: "BIGINT",
    26: "INT128",
    10: "FLOAT",
    27: "DOUBLE PRECISION",
    24: "DECFLOAT(16)",
    25: "DECFLOAT(34)",
    12: "DATE",
    13: "TIME",
    35: "TIMESTAMP",
    28: "TIME WITH TIME ZONE",
    29: "TIMESTAMP WITH TIME ZONE",
    14: "CHAR",
    37: "VARCHAR",
    261: "BLOB",
    23: "BOOLEAN",
}
_ENTEROS = {7, 8, 16, 26}
# RDB$REF_CONSTRAINTS.RDB$DELETE_RULE -> valor de `al_borrar` en el manifiesto.
_REGLA_BORRADO = {
    "CASCADE": "cascade",
    "RESTRICT": "restrict",
    "NO ACTION": "restrict",
    "SET NULL": "set_null",
    "SET DEFAULT": "set_default",
}

_SQL_TABLAS = "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 AND RDB$VIEW_BLR IS NULL"

_SQL_COLUMNAS = """
SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, f.RDB$FIELD_SUB_TYPE,
       f.RDB$FIELD_LENGTH, f.RDB$CHARACTER_LENGTH, f.RDB$FIELD_PRECISION, f.RDB$FIELD_SCALE,
       rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG, rf.RDB$FIELD_POSITION, TRIM(cs.RDB$CHARACTER_SET_NAME),
       TRIM(rf.RDB$FIELD_SOURCE)
FROM RDB$RELATION_FIELDS rf
JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
LEFT JOIN RDB$CHARACTER_SETS cs ON cs.RDB$CHARACTER_SET_ID = f.RDB$CHARACTER_SET_ID
WHERE rf.RDB$RELATION_NAME = ?
ORDER BY rf.RDB$FIELD_POSITION
"""

_SQL_LLAVE_PRIMARIA = """
SELECT TRIM(s.RDB$FIELD_NAME)
FROM RDB$RELATION_CONSTRAINTS rc
JOIN RDB$INDEX_SEGMENTS s ON s.RDB$INDEX_NAME = rc.RDB$INDEX_NAME
WHERE rc.RDB$RELATION_NAME = ? AND rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY'
ORDER BY s.RDB$FIELD_POSITION
"""

_SQL_LLAVES_FORANEAS = """
SELECT TRIM(rc.RDB$CONSTRAINT_NAME), TRIM(s.RDB$FIELD_NAME),
       TRIM(rc2.RDB$RELATION_NAME), TRIM(s2.RDB$FIELD_NAME), TRIM(ref.RDB$DELETE_RULE)
FROM RDB$RELATION_CONSTRAINTS rc
JOIN RDB$REF_CONSTRAINTS ref ON ref.RDB$CONSTRAINT_NAME = rc.RDB$CONSTRAINT_NAME
JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = ref.RDB$CONST_NAME_UQ
JOIN RDB$INDEX_SEGMENTS s ON s.RDB$INDEX_NAME = rc.RDB$INDEX_NAME
JOIN RDB$INDEX_SEGMENTS s2 ON s2.RDB$INDEX_NAME = rc2.RDB$INDEX_NAME
                          AND s2.RDB$FIELD_POSITION = s.RDB$FIELD_POSITION
WHERE rc.RDB$RELATION_NAME = ? AND rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY'
"""


class TablaInexistente(LookupError):
    pass


def nombre_tipo(tipo: int, subtipo: int | None, precision: int | None, escala: int | None) -> str:
    """Nombre SQL legible de un tipo de RDB$FIELDS — NUMERIC/DECIMAL se
    guardan como enteros con subtipo 1/2 y escala negativa."""
    if tipo in _ENTEROS and subtipo in (1, 2):
        base = "NUMERIC" if subtipo == 1 else "DECIMAL"
        return f"{base}({precision or 18},{-(escala or 0)})"
    if tipo == 261:
        return "BLOB SUB_TYPE TEXT" if subtipo == 1 else "BLOB"
    return _TIPOS.get(tipo, f"TIPO_{tipo}")


def _describir_columna(fila: tuple) -> dict[str, Any]:
    nombre, tipo, subtipo, longitud, long_car, precision, escala, null_col, null_dom, pos, charset, dominio = fila
    nombre_sql = nombre_tipo(tipo, subtipo, precision, escala)
    categoria = (
        "decimal"
        if nombre_sql.startswith(("NUMERIC", "DECIMAL")) or tipo in (10, 27, 24, 25)
        else "entero"
        if tipo in _ENTEROS
        else "texto"
        if tipo in (14, 37)
        else "blob_texto"
        if tipo == 261 and subtipo == 1
        else "blob"
        if tipo == 261
        else {12: "fecha", 13: "hora", 28: "hora", 35: "timestamp", 29: "timestamp", 23: "booleano"}.get(tipo, "otro")
    )
    return {
        "nombre": nombre,
        "tipo": nombre_sql + (f"({long_car or longitud})" if tipo in (14, 37) else ""),
        "categoria": categoria,
        "longitud": (long_car or longitud) if tipo in (14, 37) else None,
        "nulo_permitido": not (null_col == 1 or null_dom == 1),
        "posicion": pos,
        "charset": charset,
        "dominio": None if (dominio or "").startswith("RDB$") else dominio,
    }


def listar_tablas(config: ConfigFirebird | None = None, *, con_conteo: bool = False) -> list[dict[str, Any]]:
    with conexion_solo_lectura(config) as cur:
        nombres = sorted(fila[0] for fila in cur.ejecutar(_SQL_TABLAS).filas())
        tablas = []
        for nombre in nombres:
            entrada: dict[str, Any] = {"tabla": nombre}
            if con_conteo:
                try:
                    entrada["filas"] = cur.ejecutar(f"SELECT COUNT(*) FROM {identificador_seguro(nombre)}").escalar()
                except ValueError:
                    entrada["filas"] = None  # nombre fuera del patrón habitual: no se interpola
            tablas.append(entrada)
    return tablas


def describir_tabla(tabla: str, config: ConfigFirebird | None = None, *, con_conteo: bool = True) -> dict[str, Any]:
    """Columnas (tipo, nulabilidad, charset), llave primaria, llaves foráneas
    y conteo de filas de una tabla de CONFIG."""
    tabla = tabla.strip().upper()
    with conexion_solo_lectura(config) as cur:
        columnas = [_describir_columna(f) for f in cur.ejecutar(_SQL_COLUMNAS, (tabla,)).filas()]
        if not columnas:
            raise TablaInexistente(f"La tabla {tabla!r} no existe en la base conectada.")
        llave = [f[0] for f in cur.ejecutar(_SQL_LLAVE_PRIMARIA, (tabla,)).filas()]
        foraneas = [
            {
                "restriccion": f[0],
                "columna": f[1],
                "tabla_referida": f[2],
                "columna_referida": f[3],
                "al_borrar": _REGLA_BORRADO.get((f[4] or "").upper(), "restrict"),
            }
            for f in cur.ejecutar(_SQL_LLAVES_FORANEAS, (tabla,)).filas()
        ]
        conteo = cur.ejecutar(f"SELECT COUNT(*) FROM {identificador_seguro(tabla)}").escalar() if con_conteo else None
    for c in columnas:
        c["es_llave_primaria"] = c["nombre"] in llave
    return {"tabla": tabla, "filas": conteo, "llave_primaria": llave, "llaves_foraneas": foraneas, "columnas": columnas}


def valores_distintos(tabla: str, columna: str, config: ConfigFirebird | None = None, limite: int = 50) -> list[Any]:
    """Valores distintos de una columna, calculados en Python — no con
    ``SELECT DISTINCT`` ni ``ORDER BY``: ambos obligan al servidor a construir
    una clave de orden y, sobre una columna ISO8859_1 sin el módulo INTL
    instalado, Firebird falla con "CHARACTER SET ISO8859_1 is not installed"."""
    sql = f"SELECT {identificador_seguro(columna)} FROM {identificador_seguro(tabla)}"
    with conexion_solo_lectura(config) as cur:
        vistos = {fila[0] for fila in cur.ejecutar(sql).filas()}
    return sorted(vistos, key=lambda v: (v is None, str(v)))[:limite]
