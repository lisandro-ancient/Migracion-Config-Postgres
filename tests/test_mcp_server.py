"""Round-trip real del servidor MCP por stdio con el SDK cliente oficial."""

import json
import os
import sys
from pathlib import Path

import allure
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parent.parent
pytestmark = [allure.feature("Servidor MCP"), pytest.mark.anyio]

HERRAMIENTAS = {
    "verificar_conexion",
    "listar_tablas_config",
    "describir_tabla_config",
    "generar_borrador_manifiesto",
    "capturar_snapshot",
    "listar_manifiestos_tool",
    "obtener_grafo_dependencias",
    "listar_entradas_crudas",
    "previsualizar_registro",
    "extraer_y_validar_tabla",
    "obtener_ultima_corrida",
    "iniciar_dashboard",
    "correr_pruebas",
    "verificar_postgres",
    "migrar_tabla_postgres",
    "migrar_todo_postgres",
    "consultar_registro_postgres",
    "comparar_diferencial",
}


@pytest.fixture()
def anyio_backend():
    return "asyncio"


def _parametros(datos) -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(RAIZ / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["CONFIG_MICROSIP_DATOS"] = str(datos)
    return StdioServerParameters(command=sys.executable, args=["-m", "config_microsip.mcp_server"], env=env)


async def test_expone_las_herramientas_y_valida_via_mcp(datos):
    async with stdio_client(_parametros(datos)) as (read, write), ClientSession(read, write) as sesion:
        await sesion.initialize()
        assert {t.name for t in (await sesion.list_tools()).tools} == HERRAMIENTAS

        manifiestos = json.loads((await sesion.call_tool("listar_manifiestos_tool", {})).content[0].text)
        assert manifiestos == {"prueba": [{"tabla": "elementos", "estado": "vigente"}, {"tabla": "grupos", "estado": "vigente"}]}

        previa = json.loads(
            (await sesion.call_tool("previsualizar_registro", {"fuente": "prueba", "tabla": "elementos", "id": "4"}))
            .content[0]
            .text
        )
        assert previa["estado"] == "rechazado" and "activo" in previa["motivo_rechazo"]

        reporte = json.loads(
            (await sesion.call_tool("extraer_y_validar_tabla", {"fuente": "prueba", "tabla": "elementos"})).content[0].text
        )
        assert reporte["ok_general"] is True
