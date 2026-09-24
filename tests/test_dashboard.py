"""Panel (Migration Control Center) con TestClient: cada vista con datos reales
del ledger y acciones de punta a punta dentro del proceso."""

import time

import allure
import pytest
from fastapi.testclient import TestClient

pytestmark = allure.feature("Dashboard")

VISTAS = ["/", "/fragmento/dashboard", "/jobs", "/data", "/tests", "/logs", "/agent", "/settings", "/tables", "/esquema"]


@pytest.fixture()
def cliente(datos):
    from dashboard.app import _cache_sistema, app

    _cache_sistema.update(cuando=0.0, valor=None)
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("url", VISTAS)
def test_todas_las_vistas_cargan_sin_datos(cliente, url):
    r = cliente.get(url)
    assert r.status_code == 200
    assert "Centro de control de migración" in r.text or url.startswith("/fragmento")


def test_navegacion_marca_la_vista_activa(cliente):
    assert 'href="/jobs" class="active" aria-current="page"' in cliente.get("/jobs").text
    assert 'href="/data" class="active"' in cliente.get("/data").text


def test_dashboard_vacio_no_inventa_numeros(cliente):
    html = cliente.get("/").text
    assert "Aún no hay trabajos de migración" in html and "Aún no hay comparación diferencial" in html
    assert "1,245,832" not in html  # el número de demostración del diseño original


def test_404(cliente):
    assert cliente.get("/jobs/nope").status_code == 404
    assert cliente.get("/corrida/nope").status_code == 404


def test_validar_una_tabla_desde_el_panel(cliente):
    r = cliente.post("/fuente/prueba/tabla/elementos/extraer", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/corrida/")
    detalle = cliente.get(r.headers["location"]).text
    assert "Todas las verificaciones pasaron" in detalle and "Dólar ñandú" in detalle and "Filas rechazadas" in detalle


def test_error_de_accion_se_muestra(cliente, datos):
    (datos / "fixtures/prueba/elementos_raw_snapshot.json").unlink()
    r = cliente.post("/fuente/prueba/tabla/elementos/extraer")
    assert "FixtureInexistente" in r.text
    assert "elementos" in cliente.get("/logs").text


def test_suite_desconocida_se_rechaza(cliente):
    assert "Suite desconocida" in cliente.post("/tests/run", data={"suite": "nope"}).text


def test_exportar_logs_csv(cliente):
    r = cliente.get("/logs/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0] == "hora,tabla,error,detalle,enlace"


def test_agente_muestra_decisiones_abiertas(cliente, datos):
    ruta = datos / "fuentes/prueba/manifiestos/grupos.yaml"
    ruta.write_text(
        "# - TIPO: CHAR(1) con valores observados ['A'] — ¿catálogo derivado?\n"
        + ruta.read_text().replace("estado: vigente", "estado: borrador")
    )
    html = cliente.get("/agent").text
    assert "prueba.grupos" in html and "catálogo derivado" in html and "borrador" in html


def _esperar(cliente, url, marcador, timeout=60):
    fin = time.time() + timeout
    while time.time() < fin:
        html = cliente.get(url).text
        if marcador not in html:
            return html
        time.sleep(0.3)
    raise AssertionError(f"{url} siguió mostrando {marcador!r}")


def test_trabajo_desde_el_panel_y_kpis_reales(cliente, pg):
    r = cliente.post("/jobs", data={"fuente": "prueba"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/jobs/")
    job_url = r.headers["location"]
    html = _esperar(cliente, job_url.replace("/jobs/", "/fragmento/jobs/"), 'data-estado="en_progreso"')
    assert 'data-estado="ok"' in html and "2/2" in html
    tablero = cliente.get("/").text
    assert 'id="kpi-migrated">7<' in tablero and 'id="kpi-errors">0<' in tablero and 'id="kpi-pending">0<' in tablero
    assert "7 · 100.0%" in tablero  # dona: coincidencias
    assert "Completado" in cliente.get("/jobs").text
    datos_html = cliente.get("/data").text
    assert "Idéntica" in datos_html and "elementos" in datos_html


def test_comparacion_desde_el_panel_detecta_desviacion(cliente, pg):
    from config_microsip.orquestador import migrar_todo

    migrar_todo("prueba")
    pg.execute("""UPDATE "prueba"."elementos" SET nombre = 'otro' WHERE elemento_id = 1""")
    r = cliente.post("/data/comparar", data={"fuente": "prueba"}, follow_redirects=False)
    assert r.status_code == 303
    html = _esperar(cliente, "/data", "Hay una comparación en curso")
    assert "Difiere" in html and "nombre" in html
    assert "Desviación diferencial" in cliente.get("/logs").text
    assert 'id="kpi-errors">1<' in cliente.get("/").text


def test_sondeo_pide_recarga_completa_al_terminar(cliente):
    """Con HX-Request y nada en curso, las vistas sondeadas piden HX-Refresh
    (así la barra lateral y el resto de la página se actualizan una vez)."""
    for url in ("/data", "/tests"):
        r = cliente.get(url, headers={"HX-Request": "true"})
        assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    from config_microsip import ledger

    job = ledger.iniciar_trabajo("prueba", "fixture", 1)
    assert cliente.get(f"/fragmento/jobs/{job}", headers={"HX-Request": "true"}).status_code == 200  # en curso: fragmento
    ledger.finalizar_trabajo(job, estado="ok")
    assert cliente.get(f"/fragmento/jobs/{job}", headers={"HX-Request": "true"}).headers.get("HX-Refresh") == "true"
