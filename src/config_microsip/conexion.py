"""Conexión de SOLO LECTURA a la base CONFIG.

Este es el único módulo que abre conexiones a Firebird, y todas pasan por
``conexion_solo_lectura()``: una transacción ``READ COMMITTED`` en modo
``READ`` (el servidor rechaza cualquier INSERT/UPDATE/DELETE/DDL con
"attempted update during read-only transaction"), que siempre termina en
ROLLBACK y cierra la conexión al salir — éxito o excepción. No hay ninguna
ruta de código en este proyecto que escriba en Firebird.

La conexión es efímera (una por operación) para no retener un attachment
contra la base CONFIG mientras el proceso está inactivo: MicroSIP la comparte
entre todas sus empresas y usuarios.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .config import ConfigFirebird

_IDENTIFICADOR = re.compile(r"^[A-Z][A-Z0-9_$]*$")
_runtime_preparado = False


class ErrorDeConexion(RuntimeError):
    """No se pudo abrir la conexión (archivo inexistente, credenciales,
    biblioteca cliente, runtime embebido mal configurado...)."""


def identificador_seguro(nombre: str) -> str:
    """Devuelve el identificador entre comillas dobles, o falla si no tiene la
    forma de un nombre de objeto de MicroSIP. Todo nombre de tabla o columna
    que se interpola en SQL pasa por aquí (los valores siempre van como
    parámetros)."""
    nombre = nombre.strip().upper()
    if not _IDENTIFICADOR.match(nombre):
        raise ValueError(f"Identificador no válido: {nombre!r}")
    return f'"{nombre}"'


def _preparar_runtime(config: ConfigFirebird) -> None:
    """Configura, una sola vez por proceso, lo que el motor necesita antes de
    la primera conexión:

    - ``fb_client_library``: ruta explícita a fbclient, para no depender del
      orden del PATH.
    - ``FIREBIRD`` + directorio de trabajo: el motor embebido resuelve sus
      bibliotecas ICU con una ruta relativa al cwd del proceso, no solo con la
      variable ``FIREBIRD`` (mismo hallazgo que ``~/mcp-firebird/run_mcp.sh``).
      El cambio de cwd es permanente y de todo el proceso a propósito —
      restaurarlo tras cada conexión sería una carrera entre hilos del
      dashboard—; por eso todo el proyecto trabaja con rutas absolutas.
    """
    global _runtime_preparado
    if _runtime_preparado:
        return
    import firebird.driver as fb

    if config.biblioteca_cliente:
        fb.driver_config.fb_client_library.value = config.biblioteca_cliente
    if config.directorio_runtime:
        os.environ["FIREBIRD"] = config.directorio_runtime
        if config.embebido:
            os.chdir(config.directorio_runtime)
    _runtime_preparado = True


class CursorSoloLectura:
    """Envoltura mínima: ejecutar y leer filas como listas de dicts o de
    tuplas. No expone commit ni la conexión."""

    def __init__(self, cursor):
        self._cursor = cursor

    def ejecutar(self, sql: str, parametros: tuple | None = None) -> CursorSoloLectura:
        self._cursor.execute(sql, parametros or ())
        return self

    def filas(self) -> list[tuple]:
        return list(self._cursor.fetchall())

    def una(self) -> tuple | None:
        return self._cursor.fetchone()

    def escalar(self) -> Any:
        """Primera columna de la primera fila (p. ej. un COUNT(*)); falla si no hay filas."""
        fila = self._cursor.fetchone()
        if fila is None:
            raise LookupError("La consulta no devolvió filas.")
        return fila[0]

    def columnas(self) -> list[str]:
        return [d[0] for d in (self._cursor.description or [])]

    def dicts(self) -> list[dict[str, Any]]:
        nombres = self.columnas()
        return [dict(zip(nombres, fila, strict=True)) for fila in self._cursor.fetchall()]


@contextmanager
def conexion_solo_lectura(config: ConfigFirebird | None = None) -> Iterator[CursorSoloLectura]:
    config = config or ConfigFirebird.desde_entorno()
    _preparar_runtime(config)
    import firebird.driver as fb

    try:
        con = fb.connect(config.dsn(), user=config.usuario, password=config.password, charset=config.charset)
    except Exception as exc:
        raise ErrorDeConexion(f"No se pudo conectar a {config.dsn()}: {exc}") from exc

    try:
        if not config.charset:
            # Con charset NONE, firebird-driver decodifica el texto con la
            # codificación preferida del sistema (UTF-8 en macOS) y revienta con
            # la primera "ó" en ISO8859_1. Cada cursor copia `_encoding` de la
            # conexión al crearse, así que se fija aquí, antes de abrir ninguno.
            con._encoding = config.codificacion
        tpb = fb.tpb(fb.Isolation.READ_COMMITTED_RECORD_VERSION, access_mode=fb.TraAccessMode.READ)
        transaccion = con.transaction_manager(tpb, default_action=fb.DefaultAction.ROLLBACK)
        transaccion.begin()
        try:
            cursor = transaccion.cursor()
            try:
                yield CursorSoloLectura(cursor)
            finally:
                cursor.close()
        finally:
            transaccion.rollback()
            transaccion.close()
    finally:
        con.close()


TABLAS_EJE_CONFIG = ("EMPRESAS", "USUARIOS")

_SQL_CASCADAS_EJE = """
SELECT TRIM(rc2.RDB$RELATION_NAME), COUNT(*)
FROM RDB$REF_CONSTRAINTS ref
JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = ref.RDB$CONST_NAME_UQ
WHERE rc2.RDB$RELATION_NAME IN ('EMPRESAS', 'USUARIOS') AND TRIM(ref.RDB$DELETE_RULE) = 'CASCADE'
GROUP BY 1
"""


def diagnosticar_base_config(cur: CursorSoloLectura) -> dict[str, Any]:
    """¿La base conectada tiene la forma de la base CONFIG? CONFIG es una base
    por instalación, hermana de las bases de empresa, cuyo eje son EMPRESAS y
    USUARIOS: casi todo lo demás cuelga de ellas con borrado en cascada. Una
    base de empresa (p. ej. APPCO.FDB) no tiene ninguna de las dos tablas.
    Se verifica esa forma, no el nombre del archivo."""
    existentes = {
        fila[0]
        for fila in cur.ejecutar(
            "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS "
            "WHERE RDB$RELATION_NAME IN ('EMPRESAS', 'USUARIOS') AND RDB$VIEW_BLR IS NULL"
        ).filas()
    }
    cascadas = {tabla: n for tabla, n in cur.ejecutar(_SQL_CASCADAS_EJE).filas()}
    faltan = [t for t in TABLAS_EJE_CONFIG if t not in existentes]
    sin_cascadas = [t for t in TABLAS_EJE_CONFIG if t in existentes and not cascadas.get(t)]
    es_config = not faltan and not sin_cascadas
    if es_config:
        motivo = None
    elif faltan:
        motivo = (
            f"No existen {', '.join(faltan)}: esta no es la base CONFIG (parece una base de empresa). "
            "Apunta FIREBIRD_DATABASE al CONFIG.FDB de la instalación, en la misma carpeta que las bases de empresa."
        )
    else:
        motivo = f"Existen EMPRESAS y USUARIOS pero sin llaves foráneas en cascada hacia {', '.join(sin_cascadas)}; revisar."
    return {
        "es_base_config": es_config,
        "tablas_eje": {t: t in existentes for t in TABLAS_EJE_CONFIG},
        "fk_en_cascada_hacia": {t: cascadas.get(t, 0) for t in TABLAS_EJE_CONFIG},
        "motivo": motivo,
    }


def verificar_conexion(config: ConfigFirebird | None = None) -> dict[str, Any]:
    """Abre una conexión, confirma con el propio servidor que la transacción
    es de solo lectura (``MON$TRANSACTIONS.MON$READ_ONLY``) y devuelve datos
    básicos de la base — sin contraseña. Nunca lanza: devuelve ``ok: False``
    con el motivo, para que la CLI, el MCP y el dashboard lo muestren tal cual."""
    try:
        config = config or ConfigFirebird.desde_entorno()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        with conexion_solo_lectura(config) as cur:
            solo_lectura = cur.ejecutar(
                "SELECT MON$READ_ONLY FROM MON$TRANSACTIONS WHERE MON$TRANSACTION_ID = CURRENT_TRANSACTION"
            ).una()
            ods = cur.ejecutar("SELECT MON$ODS_MAJOR, MON$ODS_MINOR, TRIM(MON$DATABASE_NAME) FROM MON$DATABASE").una()
            version = cur.ejecutar("SELECT RDB$GET_CONTEXT('SYSTEM', 'ENGINE_VERSION') FROM RDB$DATABASE").una()
            tablas = cur.ejecutar(
                "SELECT COUNT(*) FROM RDB$RELATIONS WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 AND RDB$VIEW_BLR IS NULL"
            ).una()
            diagnostico = diagnosticar_base_config(cur)
    except Exception as exc:
        return {"ok": False, "conexion": config.descripcion_segura(), "error": str(exc)}
    return {
        "ok": True,
        "conexion": config.descripcion_segura(),
        "transaccion_solo_lectura": bool(solo_lectura and solo_lectura[0] == 1),
        "version_motor": version[0] if version else None,
        "ods": f"{ods[0]}.{ods[1]}" if ods else None,
        "archivo": ods[2] if ods else None,
        "tablas_de_usuario": tablas[0] if tablas else None,
        **diagnostico,
    }
