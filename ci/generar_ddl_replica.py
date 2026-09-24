"""Genera ci/config_replica.sql: la ESTRUCTURA de la base CONFIG real (tablas,
tipos, NOT NULL, llaves primarias y foráneas con su regla de borrado), sin un
solo dato. La CI crea con ella un Firebird de verdad y lo llena con
ci/datos_replica.sql (filas inventadas).

Se corre a mano, contra la CONFIG real y en solo lectura, cuando cambia la
estructura de CONFIG:

    python ci/generar_ddl_replica.py > ci/config_replica.sql
"""

from __future__ import annotations

import sys
from collections import defaultdict

from config_microsip.conexion import conexion_solo_lectura, verificar_conexion

TIPOS = {
    7: "SMALLINT",
    8: "INTEGER",
    16: "BIGINT",
    10: "FLOAT",
    27: "DOUBLE PRECISION",
    12: "DATE",
    13: "TIME",
    35: "TIMESTAMP",
    23: "BOOLEAN",
    26: "INT128",
}


def tipo_sql(tipo, subtipo, longitud, long_car, precision, escala, charset) -> str:
    if tipo in (7, 8, 16, 26) and subtipo in (1, 2):
        return f"{'NUMERIC' if subtipo == 1 else 'DECIMAL'}({precision or 18},{-(escala or 0)})"
    if tipo in (14, 37):
        base = "CHAR" if tipo == 14 else "VARCHAR"
        return f"{base}({long_car or longitud}) CHARACTER SET {charset or 'NONE'}"
    if tipo == 261:
        return "BLOB SUB_TYPE TEXT CHARACTER SET " + (charset or "NONE") if subtipo == 1 else "BLOB SUB_TYPE BINARY"
    return TIPOS[tipo]


def main() -> int:
    estado = verificar_conexion()
    if not estado.get("es_base_config"):
        print(f"La base conectada no es CONFIG: {estado.get('motivo') or estado.get('error')}", file=sys.stderr)
        return 1
    salida = [
        "-- Estructura de la base CONFIG de MicroSIP (sin datos), generada por ci/generar_ddl_replica.py",
        f"-- desde Firebird {estado['version_motor']} · {estado['tablas_de_usuario']} tablas. No editar a mano: regenerar.",
        "",
    ]
    with conexion_solo_lectura() as cur:
        tablas = sorted(
            f[0]
            for f in cur.ejecutar(
                "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 AND RDB$VIEW_BLR IS NULL"
            ).filas()
        )
        for tabla in tablas:
            columnas = cur.ejecutar(
                """
                SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, f.RDB$FIELD_SUB_TYPE, f.RDB$FIELD_LENGTH, f.RDB$CHARACTER_LENGTH,
                       f.RDB$FIELD_PRECISION, f.RDB$FIELD_SCALE, TRIM(cs.RDB$CHARACTER_SET_NAME), rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG
                FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
                LEFT JOIN RDB$CHARACTER_SETS cs ON cs.RDB$CHARACTER_SET_ID = f.RDB$CHARACTER_SET_ID
                WHERE rf.RDB$RELATION_NAME = ? ORDER BY rf.RDB$FIELD_POSITION""",
                (tabla,),
            ).filas()
            pk = [
                f[0]
                for f in cur.ejecutar(
                    """
                SELECT TRIM(s.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS rc
                JOIN RDB$INDEX_SEGMENTS s ON s.RDB$INDEX_NAME = rc.RDB$INDEX_NAME
                WHERE rc.RDB$RELATION_NAME = ? AND rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' ORDER BY s.RDB$FIELD_POSITION""",
                    (tabla,),
                ).filas()
            ]
            lineas = [
                f'    "{n}" {tipo_sql(t, st, lg, lc, p, e, cs)}{" NOT NULL" if (nf == 1 or nd == 1) else ""}'
                for n, t, st, lg, lc, p, e, cs, nf, nd in columnas
            ]
            if pk:
                lineas.append(f'    CONSTRAINT "PK_{tabla}" PRIMARY KEY ({", ".join(chr(34) + c + chr(34) for c in pk)})')
            salida += [f'CREATE TABLE "{tabla}" (', ",\n".join(lineas), ");", ""]
        fks = defaultdict(list)
        for nombre, tabla, col, padre, col_padre, regla in cur.ejecutar("""
                SELECT TRIM(rc.RDB$CONSTRAINT_NAME), TRIM(rc.RDB$RELATION_NAME), TRIM(s.RDB$FIELD_NAME),
                       TRIM(rc2.RDB$RELATION_NAME), TRIM(s2.RDB$FIELD_NAME), TRIM(ref.RDB$DELETE_RULE)
                FROM RDB$REF_CONSTRAINTS ref
                JOIN RDB$RELATION_CONSTRAINTS rc ON rc.RDB$CONSTRAINT_NAME = ref.RDB$CONSTRAINT_NAME
                JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = ref.RDB$CONST_NAME_UQ
                JOIN RDB$INDEX_SEGMENTS s ON s.RDB$INDEX_NAME = rc.RDB$INDEX_NAME
                JOIN RDB$INDEX_SEGMENTS s2 ON s2.RDB$INDEX_NAME = rc2.RDB$INDEX_NAME AND s2.RDB$FIELD_POSITION = s.RDB$FIELD_POSITION
                ORDER BY 1, s.RDB$FIELD_POSITION""").filas():
            fks[(nombre, tabla, padre, regla)].append((col, col_padre))
    for (nombre, tabla, padre, regla), pares in sorted(fks.items()):
        cols = ", ".join(f'"{c}"' for c, _ in pares)
        cols_padre = ", ".join(f'"{c}"' for _, c in pares)
        accion = "" if regla in ("RESTRICT", "NO ACTION") else f" ON DELETE {regla}"
        salida.append(
            f'ALTER TABLE "{tabla}" ADD CONSTRAINT "{nombre}" FOREIGN KEY ({cols}) REFERENCES "{padre}" ({cols_padre}){accion};'
        )
    print("\n".join(salida))
    return 0


if __name__ == "__main__":
    sys.exit(main())
