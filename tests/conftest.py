import os
import shutil
import subprocess
from pathlib import Path

import pytest

DIR_DATOS_PRUEBA = Path(__file__).resolve().parent / "datos"

# Suite de cada módulo de prueba (marcador de pytest). Un módulo nuevo sin
# clasificar hace fallar la recolección: ninguna prueba queda fuera de las
# suites que muestra el panel.
SUITE_POR_MODULO = {
    "test_primitivas": "unit",
    "test_manifiesto_y_grafo": "unit",
    "test_harness_testing": "unit",
    "test_generador": "unit",
    "test_config": "unit",
    "test_pruebas_runner": "integration",
    "test_version": "unit",
    "test_orquestador": "integration",
    "test_firebird_real": "integration",
    "test_mcp_server": "integration",
    "test_dashboard": "integration",
    "test_migracion_postgres": "integration",
    "test_trabajos": "integration",
    "test_diferencial": "differential",
    "test_diferencial_config": "differential",
    "test_e2e": "e2e",
}


def pytest_collection_modifyitems(config, items):
    sin_suite = set()
    for item in items:
        modulo = item.module.__name__.rsplit(".", 1)[-1]
        suite = SUITE_POR_MODULO.get(modulo)
        if suite is None:
            sin_suite.add(modulo)
            continue
        item.add_marker(getattr(pytest.mark, suite))
    if sin_suite:
        raise pytest.UsageError(f"Módulos de prueba sin suite en SUITE_POR_MODULO: {sorted(sin_suite)}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Genera el reporte HTML de Allure al terminar, si el comando 'allure'
    está instalado. Nunca cambia el resultado de las pruebas.
    SKIP_ALLURE_REPORT=1 lo desactiva."""
    if os.environ.get("SKIP_ALLURE_REPORT"):
        return
    resultados = session.config.rootpath / "allure-results"
    if not resultados.is_dir() or not any(resultados.iterdir()):
        return
    allure = shutil.which("allure")
    if allure is None:
        print("\n[allure] 'allure' no está instalado: resultados crudos en allure-results/, sin reporte HTML.")
        return
    try:
        subprocess.run(
            [allure, "generate", str(resultados), "-o", str(session.config.rootpath / "allure-report"), "--clean"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        print("\n[allure] Reporte: allure-report/index.html  (abrir con: allure open allure-report)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"\n[allure] No se pudo generar el reporte (no afecta las pruebas): {exc}")


@pytest.fixture()
def datos(tmp_path, monkeypatch) -> Path:
    """Copia de los datos sintéticos en un directorio temporal, activada como
    raíz de datos (CONFIG_MICROSIP_DATOS)."""
    destino = tmp_path / "datos"
    shutil.copytree(DIR_DATOS_PRUEBA, destino)
    monkeypatch.setenv("CONFIG_MICROSIP_DATOS", str(destino))
    return destino


@pytest.fixture()
def manifiesto(datos):
    from config_microsip.manifiesto import cargar_manifiesto

    return cargar_manifiesto("prueba", "elementos")


@pytest.fixture()
def pg(datos):
    """Conexión a PostgreSQL con el esquema 'prueba' (la fuente sintética) vacío
    antes y después. Nunca toca el esquema 'config'. Se salta si PostgreSQL no
    está arriba ('docker compose up -d')."""
    from config_microsip.harness_migracion import conectar, reiniciar_esquema, verificar_postgres

    if not verificar_postgres()["ok"]:
        pytest.skip("PostgreSQL de prueba no disponible — levantar con 'docker compose up -d'")
    with conectar() as conn:
        reiniciar_esquema(conn, "prueba")
        yield conn
        reiniciar_esquema(conn, "prueba")
