"""De extremo a extremo: el sistema completo desde afuera, como lo usa una persona.

- Levanta el panel REAL (uvicorn en un subproceso, puerto libre) sobre una copia
  de los datos sintéticos, y lo maneja solo por HTTP: crear un trabajo, seguir
  su progreso, ver KPIs, correr la comparación, leer logs.
- Corre la CLI real en subprocesos (migrar-todo, consultar-postgres).
- Verifica el resultado final leyendo PostgreSQL directamente.

Necesita PostgreSQL ('docker compose up -d'); si no está, se salta.
"""

import os
import re
import socket
import subprocess
import sys
import time

import allure
import httpx
import pytest

from config_microsip.rutas import RUTA_PROYECTO

pytestmark = allure.feature("End-to-end")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _entorno(datos) -> dict:
    env = dict(os.environ)
    env["CONFIG_MICROSIP_DATOS"] = str(datos)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RUTA_PROYECTO / "src"), str(RUTA_PROYECTO)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    return env


@pytest.fixture()
def servidor(pg, datos):
    puerto = _puerto_libre()
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--port", str(puerto), "--log-level", "warning"],
        cwd=RUTA_PROYECTO,
        env=_entorno(datos),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{puerto}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise AssertionError("El panel no arrancó: " + proceso.stdout.read().decode(errors="replace")[-2000:])
        with httpx.Client(base_url=base, timeout=30) as cliente:
            yield cliente
    finally:
        proceso.terminate()
        proceso.wait(timeout=10)


def _esperar(cliente, url, mientras, timeout=90):
    fin = time.time() + timeout
    while time.time() < fin:
        html = cliente.get(url).text
        if mientras not in html:
            return html
        time.sleep(0.5)
    raise AssertionError(f"Tiempo agotado esperando {url}")


def test_flujo_completo_por_http(servidor, pg):
    # 1. Panel vacío
    assert "Aún no hay trabajos de migración" in servidor.get("/").text

    # 2. Crear un trabajo de migración como lo haría el botón "+ New Migration"
    r = servidor.post("/jobs", data={"fuente": "prueba"})
    assert r.status_code == 303
    job_url = r.headers["location"]
    job_id = job_url.rsplit("/", 1)[-1]

    # 3. Seguir su progreso por polling hasta que termine
    fragmento = _esperar(servidor, f"/fragmento/jobs/{job_id}", 'data-estado="en_progreso"')
    assert 'data-estado="ok"' in fragmento

    # 4. PostgreSQL tiene exactamente lo esperado
    assert pg.execute('SELECT count(*) FROM "prueba"."grupos"').fetchone()[0] == 2
    assert pg.execute('SELECT count(*) FROM "prueba"."elementos"').fetchone()[0] == 5
    assert pg.execute('SELECT nombre FROM "prueba"."elementos" WHERE elemento_id = 5').fetchone()[0] == "Dólar ñandú"

    # 5. El tablero muestra los números reales
    tablero = servidor.get("/").text
    assert re.search(r'id="kpi-source">8<', tablero) and re.search(r'id="kpi-migrated">7<', tablero)
    assert 'id="kpi-errors">0<' in tablero and "7 · 100.0%" in tablero and f"#{job_id}" in tablero

    # 6. Alguien altera PostgreSQL por fuera: la comparación lo detecta
    pg.execute("""UPDATE "prueba"."grupos" SET nombre = 'alterado' WHERE grupo_id = 10""")
    assert servidor.post("/data/comparar", data={"fuente": "prueba"}).status_code == 303
    datos = _esperar(servidor, "/data", "Hay una comparación en curso")
    assert "Difiere" in datos and "alterado" in datos
    assert "Desviación diferencial" in servidor.get("/logs").text
    assert "Desviación diferencial" in servidor.get("/logs/export.csv").text

    # 7. Volver a migrar repara la desviación (carga espejo) y el diferencial vuelve a verde
    job2 = servidor.post("/jobs", data={"fuente": "prueba"}).headers["location"].rsplit("/", 1)[-1]
    assert 'data-estado="ok"' in _esperar(servidor, f"/fragmento/jobs/{job2}", 'data-estado="en_progreso"')
    assert pg.execute('SELECT nombre FROM "prueba"."grupos" WHERE grupo_id = 10').fetchone()[0] == "Grupo diez"
    assert "Idéntica" in servidor.get("/data").text

    # 8. Historial con los dos trabajos
    trabajos_html = servidor.get("/jobs").text
    assert trabajos_html.count("Completado") >= 2


def test_cli_de_extremo_a_extremo(pg, datos):
    env = _entorno(datos)
    cli = [sys.executable, "-m", "config_microsip.cli"]
    migrar = subprocess.run(
        [*cli, "migrar-todo", "--fuente", "prueba"], cwd=RUTA_PROYECTO, env=env, capture_output=True, text=True, timeout=120
    )
    assert migrar.returncode == 0, migrar.stdout + migrar.stderr
    assert "grupos" in migrar.stdout and "elementos" in migrar.stdout
    consulta = subprocess.run(
        [*cli, "consultar-postgres", "--fuente", "prueba", "--tabla", "elementos", "--id", "5"],
        cwd=RUTA_PROYECTO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert consulta.returncode == 0 and "Dólar ñandú" in consulta.stdout
    faltante = subprocess.run(
        [*cli, "consultar-postgres", "--fuente", "prueba", "--tabla", "elementos", "--id", "4"],
        cwd=RUTA_PROYECTO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert faltante.returncode == 1  # la fila rechazada nunca llega a PostgreSQL
