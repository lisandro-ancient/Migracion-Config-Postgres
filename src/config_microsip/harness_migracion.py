"""Harness de Migración: lleva el candidato (ya validado contra el origen) a
PostgreSQL y verifica, consultando PostgreSQL, que quedó idéntico.

Flujo por tabla (lo orquesta orquestador.migrar_a_postgres):

1. **Esquema** — DDL generado del manifiesto (``ddl_tabla``): un esquema de
   PostgreSQL por fuente (``config``), una tabla por manifiesto, llave primaria,
   NOT NULL, CHECK para códigos de catálogos derivados y llaves foráneas hacia
   las tablas padre **con la misma regla de borrado que en CONFIG** (``al_borrar``
   del catálogo): borrar una empresa o un usuario en PostgreSQL arrastra su
   configuración igual que en el origen. Las FK son DEFERRABLE para poder cargar
   autorreferencias (USUARIOS.ROL_ID -> USUARIOS) en una sola transacción.
2. **Carga espejo** — en una transacción: upsert de cada fila del candidato y
   borrado de las filas que ya no existen en el origen. Es idempotente: correr
   la migración dos veces deja lo mismo. El borrado respeta las cascadas, igual
   que en el origen.
3. **Verificación en PostgreSQL** — conteo, comparación fila por fila y columna
   por columna contra el candidato, e integridad referencial consultada.

Firebird no se toca aquí: este módulo solo recibe filas ya extraídas.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import Any

from .config import ConfigPostgres
from .manifiesto import CatalogoManifiesto, Manifiesto, cargar_manifiesto, listar_manifiestos

TIPO_PG = {
    "entero": "BIGINT",
    "texto": "TEXT",
    "bandera_sn": "BOOLEAN",
    "booleano": "BOOLEAN",
    "catalogo_normalizado": "TEXT",
    "decimal": "NUMERIC",  # sin precisión fija: conserva la exactitud del origen
    "decimal_con_signo": "NUMERIC",
    "fecha": "DATE",
    "hora": "TIME",
    "timestamp": "TIMESTAMP",
}

# RESTRICT de Firebird -> NO ACTION: mismo efecto al confirmar la transacción,
# pero diferible (RESTRICT de PostgreSQL se evalúa de inmediato y rompería la
# carga de autorreferencias).
_ON_DELETE = {
    "cascade": "CASCADE",
    "restrict": "NO ACTION",
    "set_null": "SET NULL",
    "set_default": "SET DEFAULT",
    None: "NO ACTION",
}


class ErrorDeMigracion(RuntimeError):
    pass


def _q(nombre: str) -> str:
    """Identificador de PostgreSQL entre comillas (nombres del manifiesto)."""
    return '"' + nombre.replace('"', '""') + '"'


def nombre_calificado(manifiesto: Manifiesto) -> str:
    return f"{_q(manifiesto.fuente)}.{_q(manifiesto.tabla_destino)}"


# --- relaciones entre manifiestos ---------------------------------------------


def manifiesto_padre(manifiesto: Manifiesto, catalogo: CatalogoManifiesto) -> Manifiesto | None:
    """El manifiesto de la misma fuente cuya tabla de origen es la que referencia
    el catálogo (o el propio manifiesto en una autorreferencia)."""
    if catalogo.tipo != "tabla":
        return None
    if catalogo.tabla.upper() == manifiesto.tabla_origen.upper():
        return manifiesto
    for tabla in listar_manifiestos(manifiesto.fuente):
        candidato = cargar_manifiesto(manifiesto.fuente, tabla)
        if candidato.tabla_origen.upper() == catalogo.tabla.upper():
            return candidato
    return None


def llaves_foraneas(manifiesto: Manifiesto) -> list[dict[str, Any]]:
    """Las FK que tendrá la tabla en PostgreSQL, resueltas contra los
    manifiestos padre. Una FK hacia una tabla sin manifiesto no se crea (se
    reporta en ``fk_omitidas``)."""
    resultado = []
    for campo in manifiesto.campos:
        if not campo.catalogo_fk:
            continue
        catalogo = manifiesto.catalogo(campo.catalogo_fk)
        if catalogo.tipo != "tabla":
            continue
        padre = manifiesto_padre(manifiesto, catalogo)
        resultado.append(
            {
                "columna": campo.destino,
                "catalogo": catalogo.nombre,
                "tabla_padre": padre.tabla_destino if padre else None,
                "fuente_padre": padre.fuente if padre else None,
                "columna_padre": catalogo.columnas[0],
                "al_borrar": catalogo.al_borrar,
            }
        )
    return resultado


def orden_de_migracion(fuente: str, tablas: list[str] | None = None) -> list[str]:
    """Manifiestos de una fuente en orden padre -> hijo (las autorreferencias
    no cuentan como dependencia)."""
    tablas = tablas or listar_manifiestos(fuente)
    manifiestos = {t: cargar_manifiesto(fuente, t) for t in tablas}
    por_destino = {m.tabla_destino: t for t, m in manifiestos.items()}
    grafo = {}
    for t, m in manifiestos.items():
        padres = {fk["tabla_padre"] for fk in llaves_foraneas(m)} - {None, m.tabla_destino}
        grafo[t] = [por_destino[p] for p in padres if p in por_destino]
    try:
        return list(TopologicalSorter(grafo).static_order())
    except CycleError as exc:
        raise ErrorDeMigracion(f"Dependencias cíclicas entre tablas de '{fuente}': {exc}") from exc


# --- DDL ----------------------------------------------------------------------


def ddl_tabla(manifiesto: Manifiesto) -> str:
    """CREATE TABLE IF NOT EXISTS de la tabla destino, derivado del manifiesto."""
    lineas = []
    for campo in manifiesto.campos:
        tipo = TIPO_PG[campo.regla]
        lineas.append(f"    {_q(campo.destino)} {tipo}{'' if campo.nulo_permitido else ' NOT NULL'}")
    lineas.append(
        f"    CONSTRAINT {_q('pk_' + manifiesto.tabla_destino)} PRIMARY KEY ({', '.join(_q(k) for k in manifiesto.llaves)})"
    )

    for campo in manifiesto.campos:
        if campo.catalogo_dominio:
            codigos = ", ".join("'" + c.replace("'", "''") + "'" for c in manifiesto.catalogo(campo.catalogo_dominio).dominio())
            lineas.append(
                f"    CONSTRAINT {_q(f'ck_{manifiesto.tabla_destino}_{campo.destino}')} CHECK ({_q(campo.destino)} IN ({codigos}))"
            )

    omitidas = []
    for fk in llaves_foraneas(manifiesto):
        if fk["tabla_padre"] is None:
            omitidas.append(fk)
            continue
        nombre_fk = f"fk_{manifiesto.tabla_destino}_{fk['columna']}"
        lineas.append(
            f"    CONSTRAINT {_q(nombre_fk)} FOREIGN KEY ({_q(fk['columna'])}) "
            f"REFERENCES {_q(fk['fuente_padre'])}.{_q(fk['tabla_padre'])} ({_q(fk['columna_padre'])}) "
            f"ON DELETE {_ON_DELETE[fk['al_borrar']]} DEFERRABLE INITIALLY DEFERRED"
        )

    encabezado = [
        f"-- {manifiesto.fuente}.{manifiesto.tabla_origen} (Firebird) -> {manifiesto.fuente}.{manifiesto.tabla_destino} (PostgreSQL)",
        "-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.",
    ]
    encabezado += [f"-- FK omitida: {fk['columna']} -> {fk['catalogo']} (no hay manifiesto de la tabla padre)" for fk in omitidas]
    return "\n".join(encabezado) + (
        f"\nCREATE SCHEMA IF NOT EXISTS {_q(manifiesto.fuente)};\n"
        f"CREATE TABLE IF NOT EXISTS {nombre_calificado(manifiesto)} (\n" + ",\n".join(lineas) + "\n);\n"
    )


def ddl_fuente(fuente: str) -> str:
    return "\n".join(ddl_tabla(cargar_manifiesto(fuente, t)) for t in orden_de_migracion(fuente))


# --- conexión y esquema -------------------------------------------------------


def conectar(config: ConfigPostgres | None = None):
    import psycopg

    config = config or ConfigPostgres.desde_entorno()
    try:
        # autocommit: cada sentencia suelta se confirma sola, y la carga usa un
        # bloque conn.transaction() explícito, que así es una transacción real y
        # no un savepoint dentro de una transacción implícita sin confirmar.
        return psycopg.connect(config.conninfo(), autocommit=True)
    except psycopg.OperationalError as exc:
        raise ErrorDeMigracion(
            f"No se pudo conectar a PostgreSQL en {config.host}:{config.puerto} — ¿corriste 'docker compose up -d'? ({exc})"
        ) from exc


def verificar_postgres(config: ConfigPostgres | None = None) -> dict[str, Any]:
    config = config or ConfigPostgres.desde_entorno()
    try:
        with conectar(config) as conn:
            version = conn.execute("SHOW server_version").fetchone()[0]
    except Exception as exc:
        return {"ok": False, "conexion": config.descripcion_segura(), "error": str(exc)}
    return {"ok": True, "conexion": config.descripcion_segura(), "version": version}


def tabla_existe(conn, manifiesto: Manifiesto) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s)",
        (manifiesto.fuente, manifiesto.tabla_destino),
    ).fetchone()[0]


def reiniciar_esquema(conn, fuente: str) -> None:
    """DROP SCHEMA ... CASCADE del destino (solo PostgreSQL local; nunca Firebird)."""
    conn.execute(f"DROP SCHEMA IF EXISTS {_q(fuente)} CASCADE")
    conn.commit()


def asegurar_tabla(conn, manifiesto: Manifiesto) -> str:
    """Crea la tabla si no existe. Falla con un mensaje claro si falta una tabla
    padre (hay que migrarla primero, o usar migrar-todo)."""
    for fk in llaves_foraneas(manifiesto):
        if fk["tabla_padre"] and fk["tabla_padre"] != manifiesto.tabla_destino:
            existe = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s)",
                (fk["fuente_padre"], fk["tabla_padre"]),
            ).fetchone()[0]
            if not existe:
                raise ErrorDeMigracion(
                    f"La tabla padre {fk['fuente_padre']}.{fk['tabla_padre']} todavía no existe en PostgreSQL "
                    f"(FK {manifiesto.tabla_destino}.{fk['columna']}). Mígrala primero o usa 'migrar-todo'."
                )
    if tabla_existe(conn, manifiesto):
        verificar_esquema_vigente(conn, manifiesto)
    ddl = ddl_tabla(manifiesto)
    conn.execute(ddl)
    from . import __version__

    conn.execute(
        f"COMMENT ON TABLE {nombre_calificado(manifiesto)} IS "
        f"'{manifiesto.fuente}.{manifiesto.tabla_origen} — config-microsip {__version__}'"
    )
    conn.commit()
    return ddl


# Tipo de PostgreSQL (information_schema.columns.data_type) de cada tipo que genera ddl_tabla.
_TIPO_INFORMATION_SCHEMA = {
    "BIGINT": "bigint",
    "TEXT": "text",
    "BOOLEAN": "boolean",
    "NUMERIC": "numeric",
    "DATE": "date",
    "TIME": "time without time zone",
    "TIMESTAMP": "timestamp without time zone",
}


def verificar_esquema_vigente(conn, manifiesto: Manifiesto) -> None:
    """Una tabla ya existente debe tener exactamente las columnas y tipos que pide
    el manifiesto actual. ``CREATE TABLE IF NOT EXISTS`` nunca altera una tabla,
    así que si una versión nueva del proyecto (o del manifiesto) agrega, quita o
    cambia una columna, la carga fallaría con un error confuso: aquí se detecta
    antes y se dice qué hacer. PostgreSQL es un destino derivado de CONFIG, así
    que recrearlo es seguro."""
    en_pg = {
        nombre: tipo
        for nombre, tipo in conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (manifiesto.fuente, manifiesto.tabla_destino),
        ).fetchall()
    }
    esperado = {c.destino: _TIPO_INFORMATION_SCHEMA[TIPO_PG[c.regla]] for c in manifiesto.campos}
    faltan = sorted(set(esperado) - set(en_pg))
    sobran = sorted(set(en_pg) - set(esperado))
    cambian = sorted(f"{c} ({en_pg[c]} → {t})" for c, t in esperado.items() if c in en_pg and en_pg[c] != t)
    if faltan or sobran or cambian:
        detalle = "; ".join(
            parte
            for parte in (
                f"faltan {', '.join(faltan)}" if faltan else "",
                f"sobran {', '.join(sobran)}" if sobran else "",
                f"cambian {', '.join(cambian)}" if cambian else "",
            )
            if parte
        )
        raise ErrorDeMigracion(
            f"El esquema de {nombre_calificado(manifiesto)} en PostgreSQL es de una versión anterior del manifiesto "
            f"({detalle}). PostgreSQL es un destino derivado de CONFIG: recréalo con "
            f"'migrar-todo --fuente {manifiesto.fuente} --reset-esquema' (se vuelve a llenar desde el origen)."
        )


# --- carga espejo -------------------------------------------------------------


def cargar_espejo(conn, manifiesto: Manifiesto, candidato: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert del candidato + borrado de lo que ya no está en el origen, en una
    sola transacción con las FK diferidas."""
    tabla = nombre_calificado(manifiesto)
    columnas = [c.destino for c in manifiesto.campos]
    llaves = manifiesto.llaves
    no_llave = [c for c in columnas if c not in llaves]
    lista_cols = ", ".join(_q(c) for c in columnas)
    marcadores = ", ".join(["%s"] * len(columnas))
    conflicto = f"DO UPDATE SET {', '.join(f'{_q(c)} = EXCLUDED.{_q(c)}' for c in no_llave)}" if no_llave else "DO NOTHING"
    lista_llaves = ", ".join(_q(k) for k in llaves)
    try:
        with conn.transaction():
            conn.execute("SET CONSTRAINTS ALL DEFERRED")
            with conn.cursor() as cur:
                if candidato:
                    cur.executemany(
                        f"INSERT INTO {tabla} ({lista_cols}) VALUES ({marcadores}) ON CONFLICT ({lista_llaves}) {conflicto}",
                        [tuple(fila[c] for c in columnas) for fila in candidato],
                    )
                cur.execute(f"CREATE TEMP TABLE _llaves_origen ON COMMIT DROP AS SELECT {lista_llaves} FROM {tabla} WITH NO DATA")
                if candidato:
                    cur.executemany(
                        f"INSERT INTO _llaves_origen ({lista_llaves}) VALUES ({', '.join(['%s'] * len(llaves))})",
                        [tuple(fila[k] for k in llaves) for fila in candidato],
                    )
                condicion = " AND ".join(f"k.{_q(k)} = t.{_q(k)}" for k in llaves)
                cur.execute(f"DELETE FROM {tabla} t WHERE NOT EXISTS (SELECT 1 FROM _llaves_origen k WHERE {condicion})")
                eliminadas = cur.rowcount
    except Exception as exc:
        raise ErrorDeMigracion(f"La carga de {tabla} se revirtió completa: {exc}") from exc
    return {"filas_upsert": len(candidato), "filas_eliminadas": eliminadas}


# --- verificación contra PostgreSQL --------------------------------------------


def _leer_tabla(conn, manifiesto: Manifiesto) -> list[dict[str, Any]]:
    columnas = [c.destino for c in manifiesto.campos]
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(_q(c) for c in columnas)} FROM {nombre_calificado(manifiesto)}")
        return [dict(zip(columnas, fila, strict=True)) for fila in cur.fetchall()]


def validar_en_postgres(conn, manifiesto: Manifiesto, candidato: list[dict[str, Any]]) -> list[dict[str, Any]]:
    en_pg = _leer_tabla(conn, manifiesto)
    verificaciones = [
        {
            "verificacion": "postgres_conteo",
            "filas_candidato": len(candidato),
            "filas_postgres": len(en_pg),
            "ok": len(candidato) == len(en_pg),
        }
    ]

    por_llave = {manifiesto.valor_llave(f): f for f in en_pg}
    diferencias = []
    for fila in candidato:
        llave = manifiesto.valor_llave(fila)
        destino = por_llave.get(llave)
        if destino is None:
            diferencias.append(f"{manifiesto.nombre_llave}={llave}: falta en PostgreSQL")
            continue
        for columna, esperado in fila.items():
            if destino[columna] != esperado:
                diferencias.append(
                    f"{manifiesto.nombre_llave}={llave}, {columna}: candidato={esperado!r} != postgres={destino[columna]!r}"
                )
    verificaciones.append(
        {
            "verificacion": "postgres_identico_al_candidato",
            "filas_comparadas": len(candidato),
            "columnas_por_fila": len(manifiesto.campos),
            "diferencias": diferencias[:50],
            "total_diferencias": len(diferencias),
            "ok": not diferencias,
        }
    )

    huerfanos = {}
    for fk in llaves_foraneas(manifiesto):
        if not fk["tabla_padre"]:
            continue
        huerfanos[fk["columna"]] = conn.execute(
            f"SELECT COUNT(*) FROM {nombre_calificado(manifiesto)} t "
            f"LEFT JOIN {_q(fk['fuente_padre'])}.{_q(fk['tabla_padre'])} p ON t.{_q(fk['columna'])} = p.{_q(fk['columna_padre'])} "
            f"WHERE t.{_q(fk['columna'])} IS NOT NULL AND p.{_q(fk['columna_padre'])} IS NULL"
        ).fetchone()[0]
    verificaciones.append(
        {
            "verificacion": "postgres_integridad_referencial",
            "huerfanos_por_columna": huerfanos,
            "ok": all(n == 0 for n in huerfanos.values()),
        }
    )
    return verificaciones


def consultar_registro(manifiesto: Manifiesto, llave: str, config: ConfigPostgres | None = None) -> dict[str, Any] | None:
    """Un registro migrado por su llave (compuesta: 'a|b')."""
    with conectar(config) as conn:
        filas = (
            [f for f in _leer_tabla(conn, manifiesto) if manifiesto.valor_llave(f) == str(llave)]
            if tabla_existe(conn, manifiesto)
            else []
        )
    return filas[0] if filas else None
