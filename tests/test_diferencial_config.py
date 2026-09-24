"""Diferencial sobre la base CONFIG REAL: lo que hay hoy en Firebird contra lo
que quedó en PostgreSQL (esquema 'config'), tabla por tabla.

Independencia: las filas de Firebird se leen con SQL propio de esta prueba y
el valor esperado se calcula con un oráculo escrito aquí (`_esperado`), no con
el motor de reglas del proyecto — si el motor tuviera un error, esta prueba no
lo comparte. Solo lee: nunca escribe en Firebird ni en PostgreSQL.

Se salta si la base conectada no es CONFIG o si todavía no se migró
('python -m config_microsip.cli migrar-todo --firebird-real --permitir-borrador').
Si falla, PostgreSQL está desincronizado con CONFIG (o la migración tiene un error).
"""

from datetime import datetime
from decimal import Decimal

import allure
import pytest
import yaml

from config_microsip.rutas import RUTA_PROYECTO

pytestmark = allure.feature("Diferencial CONFIG real")

DIR_MANIFIESTOS = RUTA_PROYECTO / "fuentes" / "config" / "manifiestos"
MANIFIESTOS = sorted(p.stem for p in DIR_MANIFIESTOS.glob("*.yaml"))


@pytest.fixture(scope="module")
def entorno():
    from config_microsip.conexion import verificar_conexion
    from config_microsip.harness_migracion import conectar, verificar_postgres

    fb = verificar_conexion()
    if not (fb.get("ok") and fb.get("es_base_config")):
        pytest.skip(f"La base Firebird configurada no es CONFIG o no está disponible: {fb.get('motivo') or fb.get('error')}")
    if not verificar_postgres()["ok"]:
        pytest.skip("PostgreSQL no disponible — 'docker compose up -d'")
    with conectar() as pg:
        existe = pg.execute("SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'config')").fetchone()[
            0
        ]
        if not existe:
            pytest.skip("CONFIG todavía no se migró a PostgreSQL (esquema 'config' ausente)")
        yield pg


def _leer(valor):
    if hasattr(valor, "read"):
        try:
            return valor.read()
        finally:
            valor.close()
    return valor


class Rechazada(Exception):
    pass


def _esperado(regla: str, nulo_permitido: bool, valor):
    """Qué debería haber en PostgreSQL para un valor crudo de Firebird, según la
    regla declarada. Implementación independiente del motor del proyecto."""
    if isinstance(valor, str) and regla in ("texto",):
        valor = valor.strip() or None
    if valor is None:
        if nulo_permitido:
            return None
        raise Rechazada("NULL en columna obligatoria")
    if regla == "texto":
        return valor
    if regla == "entero":
        return int(valor)
    if regla in ("decimal", "decimal_con_signo"):
        return Decimal(str(valor))
    if regla == "bandera_sn":
        v = valor.strip().upper()
        if v not in ("S", "N"):
            raise Rechazada(f"bandera {valor!r}")
        return v == "S"
    if regla == "booleano":
        return bool(valor)
    if regla == "catalogo_normalizado":
        return valor.strip().upper()
    if regla == "fecha":
        return valor.date() if isinstance(valor, datetime) else valor
    if regla in ("hora", "timestamp"):
        return valor
    raise AssertionError(f"regla sin oráculo: {regla}")


@pytest.mark.parametrize("tabla", MANIFIESTOS)
def test_postgres_identico_a_firebird(entorno, tabla):
    from config_microsip.conexion import conexion_solo_lectura

    m = yaml.safe_load((DIR_MANIFIESTOS / f"{tabla}.yaml").read_text(encoding="utf-8"))
    campos = m["campos"]
    llaves = [m["llave_primaria"]] if isinstance(m["llave_primaria"], str) else m["llave_primaria"]
    origenes = [c["origen"] for c in campos]

    with conexion_solo_lectura() as cur:
        crudas = [
            [_leer(v) for v in fila]
            for fila in cur.ejecutar(
                f'SELECT {", ".join(chr(34) + o + chr(34) for o in origenes)} FROM "{m["tabla_origen"]}"'
            ).filas()
        ]
        conteo_fb = cur.ejecutar(f'SELECT COUNT(*) FROM "{m["tabla_origen"]}"').una()[0]

    esperadas, rechazadas = {}, 0
    for fila in crudas:
        try:
            normal = {
                c["destino"]: _esperado(c["regla"], c.get("nulo_permitido", False), v) for c, v in zip(campos, fila, strict=True)
            }
        except Rechazada:
            rechazadas += 1
            continue
        esperadas[tuple(normal[k] for k in llaves)] = normal

    destinos = [c["destino"] for c in campos]
    filas_pg = entorno.execute(
        f'SELECT {", ".join(chr(34) + d + chr(34) for d in destinos)} FROM "config"."{m["tabla_destino"]}"'
    ).fetchall()
    en_pg = {tuple(dict(zip(destinos, f, strict=True))[k] for k in llaves): dict(zip(destinos, f, strict=True)) for f in filas_pg}

    assert conteo_fb == len(crudas)
    assert len(filas_pg) == conteo_fb - rechazadas, (
        f"{tabla}: Firebird {conteo_fb} (−{rechazadas} rechazadas) vs PostgreSQL {len(filas_pg)}"
    )
    assert set(en_pg) == set(esperadas), (
        f"{tabla}: faltan {sorted(set(esperadas) - set(en_pg))[:5]}, sobran {sorted(set(en_pg) - set(esperadas))[:5]}"
    )
    distintas = [(k, c, esperadas[k][c], en_pg[k][c]) for k in esperadas for c in destinos if esperadas[k][c] != en_pg[k][c]]
    assert not distintas, f"{tabla}: {len(distintas)} valores distintos, p. ej. {distintas[:3]}"


def test_reglas_de_borrado_iguales_en_ambos_lados(entorno):
    """Cada FK real de CONFIG existe en PostgreSQL con la misma regla de borrado
    (CASCADE ↔ CASCADE; RESTRICT ↔ NO ACTION diferible)."""
    from config_microsip.conexion import conexion_solo_lectura

    with conexion_solo_lectura() as cur:
        en_fb = {
            (t.lower(), c.lower(), r.lower()): regla.strip()
            for t, c, r, regla in cur.ejecutar("""
            SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(s.RDB$FIELD_NAME), TRIM(rc2.RDB$RELATION_NAME), ref.RDB$DELETE_RULE
            FROM RDB$REF_CONSTRAINTS ref
            JOIN RDB$RELATION_CONSTRAINTS rc ON rc.RDB$CONSTRAINT_NAME = ref.RDB$CONSTRAINT_NAME
            JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = ref.RDB$CONST_NAME_UQ
            JOIN RDB$INDEX_SEGMENTS s ON s.RDB$INDEX_NAME = rc.RDB$INDEX_NAME""").filas()
        }
    en_pg = {
        (t, c, r): regla
        for t, c, r, regla in entorno.execute("""
        SELECT tc.table_name, kcu.column_name, ccu.table_name, rc.delete_rule
        FROM information_schema.referential_constraints rc
        JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name AND tc.table_schema = 'config'
        JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = rc.constraint_name AND kcu.table_schema = 'config'
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = rc.constraint_name AND ccu.table_schema = 'config'""").fetchall()
    }
    equivalente = {
        "CASCADE": "CASCADE",
        "RESTRICT": "NO ACTION",
        "NO ACTION": "NO ACTION",
        "SET NULL": "SET NULL",
        "SET DEFAULT": "SET DEFAULT",
    }
    assert en_fb, "CONFIG debería tener llaves foráneas"
    assert set(en_pg) == set(en_fb)
    for fk, regla in en_fb.items():
        assert en_pg[fk] == equivalente[regla], f"{fk}: Firebird {regla} vs PostgreSQL {en_pg[fk]}"
