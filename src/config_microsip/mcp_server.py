"""Servidor MCP de config_microsip: la base CONFIG de Firebird MicroSIP como
herramientas para un agente (Claude Code, Claude Desktop u otro cliente MCP).

Ninguna herramienta escribe en Firebird — todas las lecturas pasan por una
transacción READ ONLY (ver conexion.py). Las únicas que escriben algo lo hacen
en archivos de este repositorio: ``generar_borrador_manifiesto`` (un YAML),
``capturar_snapshot`` (fixtures/) y ``extraer_y_validar_tabla`` (runs/ y el
ledger).

Ejecutar (stdio): python -m config_microsip.mcp_server
Registro en Claude Code: .mcp.json en la raíz del repositorio.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__, ledger
from .grafo import describir_grafo
from .manifiesto import cargar_manifiesto, listar_fuentes, listar_manifiestos, ruta_manifiesto
from .reglas.motor import ErrorDeTransformacion, normalizar_fila
from .rutas import RUTA_PROYECTO

servidor = MCPServer(
    name="config-microsip",
    version=__version__,
    instructions=(
        "Herramientas de SOLO LECTURA sobre la base CONFIG de Firebird MicroSIP (la base del sistema, no "
        "una empresa). Flujo típico: 'verificar_conexion' -> 'listar_tablas_config' / 'describir_tabla_config' "
        "para conocer el esquema real -> 'generar_borrador_manifiesto' para una tabla -> revisar el YAML -> "
        "'capturar_snapshot' -> 'extraer_y_validar_tabla'. Si 'ok_general' es false, lee 'verificaciones' y "
        "corrige el manifiesto (o el golden) antes de reintentar. Nunca supongas la estructura de CONFIG: "
        "descríbela. Ninguna herramienta modifica Firebird. Para llevar CONFIG a PostgreSQL: "
        "'verificar_postgres' -> 'migrar_todo_postgres' (orden padre -> hijo); cada tabla solo se carga si "
        "antes pasó la validación contra el origen, y luego se verifica fila por fila en PostgreSQL."
    ),
)


@servidor.tool()
def verificar_conexion() -> dict[str, Any]:
    """Conecta a la base configurada en FIREBIRD_DATABASE, confirma con el
    servidor que la transacción es de solo lectura y devuelve versión del
    motor, ODS y número de tablas. Nunca devuelve la contraseña."""
    from .conexion import verificar_conexion as verificar

    return verificar()


@servidor.tool()
def listar_tablas_config(con_conteo: bool = False) -> list[dict[str, Any]]:
    """Tablas de usuario de la base CONFIG (sin tablas de sistema ni vistas),
    opcionalmente con su COUNT(*)."""
    from .esquema import listar_tablas

    return listar_tablas(con_conteo=con_conteo)


@servidor.tool()
def describir_tabla_config(tabla: str) -> dict[str, Any]:
    """Columnas (tipo, nulabilidad, charset), llave primaria, llaves foráneas
    reales y conteo de filas de una tabla de CONFIG."""
    from .esquema import describir_tabla

    return describir_tabla(tabla)


@servidor.tool()
def generar_borrador_manifiesto(tabla: str, fuente: str = "config", sobrescribir: bool = False) -> dict[str, Any]:
    """Escribe fuentes/<fuente>/manifiestos/<tabla>.yaml con estado 'borrador'
    a partir del esquema real (y de los valores observados en columnas CHAR(1)).
    Devuelve el YAML para revisarlo. No sobrescribe salvo que se pida."""
    from .esquema import describir_tabla, valores_distintos
    from .generador import generar_borrador

    descripcion = describir_tabla(tabla)
    destino = ruta_manifiesto(fuente, descripcion["tabla"].lower())
    if destino.exists() and not sobrescribir:
        return {
            "error": f"Ya existe {destino}. Pasa sobrescribir=true para reemplazarlo.",
            "yaml_actual": destino.read_text(encoding="utf-8"),
        }
    texto = generar_borrador(descripcion, fuente=fuente, valores_char1=lambda col: valores_distintos(descripcion["tabla"], col))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return {"ruta": str(destino), "yaml": texto}


@servidor.tool()
def capturar_snapshot(tabla: str, fuente: str = "config") -> dict[str, Any]:
    """Lee de Firebird (solo lectura) la tabla del manifiesto y sus catálogos
    tipo 'tabla' y los guarda como snapshots en fixtures/."""
    from .extract import capturar_fixtures

    return capturar_fixtures(cargar_manifiesto(fuente, tabla))


@servidor.tool()
def listar_manifiestos_tool() -> dict[str, list[dict[str, str]]]:
    """Fuentes registradas y, para cada una, sus manifiestos con su estado."""
    return {
        fuente: [{"tabla": t, "estado": cargar_manifiesto(fuente, t).estado} for t in listar_manifiestos(fuente)]
        for fuente in listar_fuentes()
    }


@servidor.tool()
def obtener_grafo_dependencias(tabla: str, fuente: str = "config") -> dict[str, Any]:
    """Nodos, aristas y orden de extracción de un manifiesto y sus catálogos."""
    return describir_grafo(cargar_manifiesto(fuente, tabla))


def _filas(manifiesto, firebird_real: bool) -> list[dict[str, Any]]:
    if firebird_real:
        from .extract import extraer_desde_firebird

        return extraer_desde_firebird(manifiesto)[0]
    from .extract import extraer_filas_desde_fixture

    return extraer_filas_desde_fixture(manifiesto)


@servidor.tool()
def listar_entradas_crudas(
    tabla: str, fuente: str = "config", limite: int = 10, firebird_real: bool = False
) -> list[dict[str, Any]]:
    """Primeras `limite` filas tal como llegan (snapshot, o la base en vivo con
    firebird_real=true), sin normalizar."""
    return _filas(cargar_manifiesto(fuente, tabla), firebird_real)[:limite]


@servidor.tool()
def previsualizar_registro(tabla: str, id: str, fuente: str = "config", firebird_real: bool = False) -> dict[str, Any]:
    """Dato crudo y resultado del motor de reglas para un registro (llave
    compuesta: valores separados por '|'), o el motivo exacto del rechazo."""
    manifiesto = cargar_manifiesto(fuente, tabla)
    fila = next((f for f in _filas(manifiesto, firebird_real) if manifiesto.valor_llave_crudo(f) == str(id)), None)
    if fila is None:
        return {"error": f"{manifiesto.nombre_llave}={id} no existe en el origen"}
    try:
        return {"id": id, "estado": "aceptado", "entrada_cruda": fila, "salida_normalizada": normalizar_fila(manifiesto, fila)}
    except ErrorDeTransformacion as exc:
        return {"id": id, "estado": "rechazado", "entrada_cruda": fila, "motivo_rechazo": str(exc)}


@servidor.tool()
def extraer_y_validar_tabla(tabla: str, fuente: str = "config", firebird_real: bool = False) -> dict[str, Any]:
    """Harness de Extracción + Harness de Testing para un manifiesto; devuelve
    comparison.json y escribe report.md y evidence/ en runs/<fuente>/<tabla>/<run_id>/."""
    from .orquestador import extraer_y_validar

    return extraer_y_validar(fuente, tabla, usar_firebird_real=firebird_real)


@servidor.tool()
def verificar_postgres() -> dict[str, Any]:
    """Conecta al PostgreSQL de destino (POSTGRES_* / docker-compose.yml) y devuelve su versión."""
    from .harness_migracion import verificar_postgres as verificar

    return verificar()


@servidor.tool()
def migrar_tabla_postgres(
    tabla: str, fuente: str = "config", firebird_real: bool = False, permitir_borrador: bool = False
) -> dict[str, Any]:
    """Extrae y valida la tabla contra el origen; solo si pasa, la carga a
    PostgreSQL (upsert + borrado espejo, FK con la regla de borrado de CONFIG) y
    verifica en PostgreSQL que quedó idéntica. Las tablas padre deben estar
    migradas antes (o usar migrar_todo_postgres)."""
    from .orquestador import migrar_a_postgres

    return migrar_a_postgres(fuente, tabla, usar_firebird_real=firebird_real, permitir_borrador=permitir_borrador)


@servidor.tool()
def migrar_todo_postgres(
    fuente: str = "config", firebird_real: bool = False, permitir_borrador: bool = False, reset_esquema: bool = False
) -> dict[str, Any]:
    """Migra todas las tablas de la fuente en orden padre -> hijo.
    reset_esquema=true borra el esquema de destino en PostgreSQL (nunca Firebird)."""
    from .orquestador import migrar_todo

    return migrar_todo(fuente, usar_firebird_real=firebird_real, permitir_borrador=permitir_borrador, reset_esquema=reset_esquema)


@servidor.tool()
def consultar_registro_postgres(tabla: str, id: str, fuente: str = "config") -> dict[str, Any]:
    """Un registro ya migrado, leído de PostgreSQL (llave compuesta: 'a|b')."""
    from .harness_migracion import consultar_registro

    fila = consultar_registro(cargar_manifiesto(fuente, tabla), id)
    return fila if fila is not None else {"error": f"{id} no está en PostgreSQL"}


@servidor.tool()
def comparar_diferencial(fuente: str = "config", firebird_real: bool = False) -> dict[str, Any]:
    """Comparación diferencial Firebird ↔ PostgreSQL de todas las tablas de la
    fuente: por tabla, filas que coinciden, difieren, faltan o sobran, y si el
    esquema de PostgreSQL coincide con el manifiesto. Queda registrada para el panel."""
    from .diferencial import comparar_fuente

    return comparar_fuente(fuente, usar_firebird_real=firebird_real)


@servidor.tool()
def obtener_ultima_corrida(tabla: str, fuente: str = "config") -> dict[str, Any]:
    """La corrida más reciente de una tabla, desde el ledger, sin ejecutar nada."""
    corridas = ledger.listar_corridas(fuente=fuente, tabla=tabla, limite=1)
    return (
        corridas[0] if corridas else {"error": f"No hay corridas para {fuente}.{tabla}. Llama a extraer_y_validar_tabla primero."}
    )


@servidor.tool()
def iniciar_dashboard(puerto: int = 8020) -> dict[str, Any]:
    """Levanta el dashboard web en segundo plano y devuelve su URL. Si ya hay
    algo escuchando en ese puerto, no lanza un segundo proceso."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", puerto)) == 0:
            return {"url": f"http://127.0.0.1:{puerto}", "ya_estaba_corriendo": True}
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--port", str(puerto)],
        cwd=RUTA_PROYECTO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"url": f"http://127.0.0.1:{puerto}", "ya_estaba_corriendo": False, "pid": proceso.pid}


def _contar(categoria: str, texto: str) -> int:
    m = re.search(rf"(\d+) {categoria}", texto)
    return int(m.group(1)) if m else 0


@servidor.tool()
def correr_pruebas(patron: str | None = None) -> dict[str, Any]:
    """Corre pytest y devuelve un resumen estructurado (pasaron/fallaron/
    saltadas). `patron` equivale a `pytest -k patron`."""
    comando = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + (["-k", patron] if patron else [])
    try:
        proceso = subprocess.run(comando, cwd=RUTA_PROYECTO, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"error": "La corrida de pruebas superó el tiempo límite (300s)."}
    salida = proceso.stdout + "\n" + proceso.stderr
    lineas = [linea for linea in salida.strip().splitlines() if linea.strip()]
    return {
        "exitoso": proceso.returncode == 0,
        "codigo_salida": proceso.returncode,
        "pasaron": _contar("passed", salida),
        "fallaron": _contar("failed", salida),
        "saltadas": _contar("skipped", salida),
        "resumen": lineas[-1] if lineas else "",
    }


def main() -> None:
    servidor.run(transport="stdio")


if __name__ == "__main__":
    main()
