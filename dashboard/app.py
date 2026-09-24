"""Migration Control Center: FastAPI + Jinja2 + HTMX (polling).

Diseño basado en ``firebird_postgresql_migration_dashboard.html``; cada número
sale de datos reales: el ledger (corridas, trabajos, comparaciones, pruebas),
la evidencia de runs/ y el estado de las conexiones. No hay contadores de
demostración.

Lo único que el panel dispara son acciones explícitas del usuario (validar,
migrar, comparar, correr pruebas), todas vía los mismos módulos que usan la CLI
y el MCP. Los trabajos largos corren en segundo plano (config_microsip.trabajos)
y el panel muestra su progreso por polling.
"""

from __future__ import annotations

import csv
import getpass
import io
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config_microsip import __version__, ledger, trabajos
from config_microsip.grafo import describir_grafo
from config_microsip.manifiesto import cargar_manifiesto, listar_fuentes, listar_manifiestos, ruta_manifiesto
from config_microsip.pruebas import SUITES, ultimo_resultado_por_suite
from config_microsip.rutas import ruta_runs

DIR_DASHBOARD = Path(__file__).resolve().parent


@asynccontextmanager
async def _vida(app: FastAPI):
    ledger.marcar_trabajos_interrumpidos()
    yield


app = FastAPI(title="Centro de control de migración", lifespan=_vida)
app.mount("/static", StaticFiles(directory=DIR_DASHBOARD / "static"), name="static")
templates = Jinja2Templates(directory=DIR_DASHBOARD / "templates")


# --- formato para las plantillas -------------------------------------------------


def _hora(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "—"


def _fecha_hora(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


def _duracion(segundos: float | None) -> str:
    if segundos is None:
        return "—"
    segundos = round(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")


def _miles(n: Any) -> str:
    return "—" if n is None else f"{int(n):,}"


def _pct(parte: Any, total: Any) -> float | None:
    return round(100 * parte / total, 1) if total else None


templates.env.filters.update(hora=_hora, fecha_hora=_fecha_hora, duracion=_duracion, miles=_miles)


# --- estado de conexiones (en caché: no abrir Firebird en cada polling) -------------

_cache_sistema: dict[str, Any] = {"cuando": 0.0, "valor": None}
TTL_SISTEMA = 20


def estado_sistema(forzar: bool = False) -> dict[str, Any]:
    if not forzar and _cache_sistema["valor"] and time.time() - _cache_sistema["cuando"] < TTL_SISTEMA:
        return _cache_sistema["valor"]
    from config_microsip.conexion import verificar_conexion
    from config_microsip.harness_migracion import verificar_postgres

    firebird, postgres = verificar_conexion(), verificar_postgres()
    valor = {
        "firebird": firebird,
        "postgres": postgres,
        "online": bool(firebird.get("ok") and postgres.get("ok")),
        "comprobado_en": time.time(),
    }
    _cache_sistema.update(cuando=time.time(), valor=valor)
    return valor


def _base(request: Request, vista: str, **contexto: Any) -> dict[str, Any]:
    ultima = ledger.listar_trabajos(limite=1)
    return {
        "request": request,
        "vista": vista,
        "version": __version__,
        "usuario": getpass.getuser(),
        "sistema": estado_sistema(),
        "ocupado": trabajos.ocupado(),
        "ultimo_trabajo_nav": ultima[0] if ultima else None,
        "errores_nav": len(errores_recientes(limite=50)),
        **contexto,
    }


def _render(request: Request, plantilla: str, vista: str, status_code: int = 200, **contexto: Any):
    return templates.TemplateResponse(request, plantilla, _base(request, vista, **contexto), status_code=status_code)


def _fuente_por_defecto() -> str | None:
    fuentes = listar_fuentes()
    return "config" if "config" in fuentes else (fuentes[0] if fuentes else None)


# --- datos derivados del ledger ------------------------------------------------

PASOS_TRABAJO = [
    ("conectando", "Conectar a Firebird"),
    ("extrayendo", "Extraer de Firebird"),
    ("validando", "Validar contra el origen"),
    ("cargando", "Cargar en PostgreSQL"),
    ("verificando", "Verificar en PostgreSQL"),
    ("comparación diferencial", "Comparación diferencial"),
]


def pasos_de(trabajo: dict | None) -> list[dict[str, str]]:
    if not trabajo:
        return []
    if trabajo["estado"] != "en_progreso":
        final = "done" if trabajo["estado"] == "ok" else "failed"
        return [
            {"nombre": n, "estado": "done" if i < len(PASOS_TRABAJO) - 1 else final} for i, (_, n) in enumerate(PASOS_TRABAJO)
        ]
    claves = [c for c, _ in PASOS_TRABAJO]
    actual = claves.index(trabajo["paso_actual"]) if trabajo.get("paso_actual") in claves else 0
    return [
        {"nombre": n, "estado": "done" if i < actual else ("running" if i == actual else "pending")}
        for i, (_, n) in enumerate(PASOS_TRABAJO)
    ]


def _detalle(fila: dict | None) -> dict:
    return json.loads(fila["detalle_json"]) if fila and fila.get("detalle_json") else {}


def _leer_json(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def errores_recientes(limite: int = 10) -> list[dict[str, Any]]:
    """Corridas fallidas y diferencias de la última comparación, como filas
    (hora, tabla, tipo de error, detalle)."""
    filas = []
    for c in ledger.listar_corridas(limite=limite, estados=("fail", "error")):
        detalle = _detalle(c)
        if c["estado"] == "error":
            tipo, _, texto = detalle.get("error", "Error").partition(":")
        else:
            comparison = _leer_json(ruta_runs() / c["fuente"] / c["tabla"] / c["run_id"] / "comparison.json") or {}
            fallidas = [v for v in comparison.get("verificaciones", []) if not v.get("ok")]
            tipo = ", ".join(v["verificacion"] for v in fallidas) or "Validación fallida"
            texto = (comparison.get("migracion_postgres") or {}).get("motivo") or f"{c['filas_falla'] or 0} filas rechazadas"
        filas.append(
            {
                "cuando": c["terminado_en"] or c["iniciado_en"],
                "tabla": c["tabla"],
                "tipo": tipo.strip(),
                "texto": texto.strip(),
                "enlace": f"/corrida/{c['run_id']}",
            }
        )
    comparacion = _ultima_comparacion_terminada()
    for t in _detalle(comparacion).get("tablas", []):
        if not t.get("ok"):
            partes = [f"{t[k]} {k}" for k in ("diferentes", "faltantes", "sobrantes") if t.get(k)]
            if t.get("error"):
                partes.append(t["error"])
            if t.get("esquema_ok") is False:
                partes.append("esquema distinto")
            filas.append(
                {
                    "cuando": comparacion["terminado_en"],
                    "tabla": t["tabla"],
                    "tipo": "Desviación diferencial",
                    "texto": ", ".join(partes) or "desviación",
                    "enlace": f"/data?id={comparacion['comparacion_id']}",
                }
            )
    return sorted(filas, key=lambda f: f["cuando"] or 0, reverse=True)[:limite]


def _ultima_comparacion_terminada() -> dict | None:
    return next((c for c in ledger.listar_comparaciones(limite=10) if c["estado"] != "en_progreso"), None)


def grafica_progreso(trabajo: dict | None) -> dict[str, Any]:
    """Serie real del trabajo: % de tablas procesadas en el tiempo (corridas
    terminadas del trabajo), lista para un <polyline> de 600x180."""
    if not trabajo:
        return {"puntos": "", "etiquetas": [], "vacio": True}
    corridas = sorted(
        (c for c in ledger.listar_corridas(job_id=trabajo["job_id"], limite=500) if c["terminado_en"]),
        key=lambda c: c["terminado_en"],
    )
    total = trabajo["tablas_total"] or 1
    inicio = trabajo["iniciado_en"]
    lapso = max((trabajo["terminado_en"] or time.time()) - inicio, 1e-6)
    puntos = [(0.0, 0.0)] + [(min((c["terminado_en"] - inicio) / lapso, 1.0), (i + 1) / total) for i, c in enumerate(corridas)]
    if trabajo["terminado_en"] and corridas:
        puntos.append((1.0, puntos[-1][1]))  # el trabajo sigue (comparación diferencial) tras la última tabla
    texto = " ".join(f"{round(x * 600, 1)},{round(175 - y * 165, 1)}" for x, y in puntos)
    formato = "%H:%M" if lapso > 90 else "%H:%M:%S"
    etiquetas = [datetime.fromtimestamp(inicio + lapso * f).strftime(formato) for f in (0, 1 / 3, 2 / 3, 1)]
    return {"puntos": texto, "etiquetas": etiquetas, "vacio": not corridas}


def dona(comparacion: dict | None) -> dict[str, Any] | None:
    if not comparacion:
        return None
    partes = {k: comparacion.get(k) or 0 for k in ("coinciden", "diferentes", "faltantes", "sobrantes")}
    total = sum(partes.values())
    if not total:
        return {"total": 0, **partes, "pct": {k: 0 for k in partes}, "gradiente": "var(--border) 0 100%"}
    pct = {k: v * 100 / total for k, v in partes.items()}
    a = pct["coinciden"]
    b = a + pct["diferentes"]
    gradiente = f"var(--green) 0 {a:.3f}%, var(--orange) {a:.3f}% {b:.3f}%, var(--red) {b:.3f}% 100%"
    return {"total": total, **partes, "pct": {k: round(v, 1) for k, v in pct.items()}, "gradiente": gradiente}


def pendientes_agente() -> list[dict[str, Any]]:
    """Decisiones abiertas en los manifiestos: lo que el agente (vía MCP) o una
    persona debe revisar. Salen de las notas que el generador dejó en cada borrador."""
    resultado = []
    for fuente in listar_fuentes():
        for tabla in listar_manifiestos(fuente):
            try:
                estado = cargar_manifiesto(fuente, tabla).estado
            except Exception as exc:
                resultado.append({"fuente": fuente, "tabla": tabla, "tipo": "invalid", "texto": str(exc)})
                continue
            notas = [
                linea[4:].strip()
                for linea in ruta_manifiesto(fuente, tabla).read_text(encoding="utf-8").splitlines()
                if linea.startswith("# - ")
            ]
            for nota in notas:
                if "catálogo derivado" in nota or "confirmar" in nota or "NOT NULL" in nota:
                    resultado.append({"fuente": fuente, "tabla": tabla, "tipo": "decision", "texto": nota})
            if estado != "vigente":
                resultado.append(
                    {
                        "fuente": fuente,
                        "tabla": tabla,
                        "tipo": "draft",
                        "texto": "El manifiesto sigue en borrador: revisa sus reglas y ponlo en estado: vigente.",
                    }
                )
    return resultado


def contexto_dashboard() -> dict[str, Any]:
    trabajo = (ledger.listar_trabajos(limite=1) or [None])[0]
    comparacion = _ultima_comparacion_terminada()
    origen = comparacion["filas_origen"] if comparacion else (trabajo["filas_origen"] if trabajo else None)
    rechazadas = (comparacion or {}).get("rechazadas") or 0
    migrables = (origen or 0) - rechazadas
    migradas = comparacion["coinciden"] if comparacion else (trabajo["filas_migradas"] if trabajo else None)
    errores_dif = sum((comparacion or {}).get(k) or 0 for k in ("diferentes", "faltantes", "sobrantes"))
    procesadas = (trabajo["tablas_ok"] + trabajo["tablas_fail"]) if trabajo else 0
    return {
        "trabajo": trabajo,
        "pasos": pasos_de(trabajo),
        "progreso_pct": _pct(procesadas, trabajo["tablas_total"]) if trabajo else None,
        "procesadas": procesadas,
        "comparacion": comparacion,
        "comparacion_en_curso": any(c["estado"] == "en_progreso" for c in ledger.listar_comparaciones(limite=3)),
        "kpi": {
            "origen": origen,
            "migradas": migradas,
            "migradas_pct": _pct(migradas, migrables)
            if migradas is not None and migrables
            else (100.0 if migradas == 0 and origen == 0 else None),
            "rechazadas": rechazadas,
            "duracion": ((trabajo["terminado_en"] or time.time()) - trabajo["iniciado_en"]) if trabajo else None,
            "errores": (trabajo["tablas_fail"] if trabajo else 0) + errores_dif,
            "tablas_fail": trabajo["tablas_fail"] if trabajo else 0,
            "errores_dif": errores_dif,
            "pendientes": max(migrables - (migradas or 0), 0) if origen is not None else None,
        },
        "grafica": grafica_progreso(trabajo),
        "dona": dona(comparacion),
        "suites": SUITES,
        "pruebas": ultimo_resultado_por_suite(),
        "actividad": ledger.actividad_reciente(limite=6),
        "errores": errores_recientes(limite=5),
        "pendientes_agente": pendientes_agente(),
        "historial": ledger.listar_trabajos(limite=5),
    }


def _recargar_si_termino(request: Request, en_curso: bool) -> Response | None:
    """Una página que se sondea mientras algo corre (HTMX) pide una recarga
    completa cuando ya no corre nada: así se actualizan también la barra
    lateral y el resto de la página, y el sondeo se detiene."""
    if request.headers.get("HX-Request") and not en_curso:
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return None


def _volver(url: str, *, error: str | None = None, mensaje: str | None = None) -> RedirectResponse:
    separador = "&" if "?" in url else "?"
    if error:
        url += f"{separador}error={quote(error)}"
    elif mensaje:
        url += f"{separador}mensaje={quote(mensaje)}"
    return RedirectResponse(url=url, status_code=303)


# --- vistas -----------------------------------------------------------------


@app.get("/")
def vista_dashboard(request: Request, error: str | None = None, mensaje: str | None = None):
    return _render(
        request,
        "dashboard.html",
        "dashboard",
        error=error,
        mensaje=mensaje,
        fuente_defecto=_fuente_por_defecto(),
        **contexto_dashboard(),
    )


@app.get("/fragmento/dashboard")
def fragmento_dashboard(request: Request):
    return _render(request, "_dashboard.html", "dashboard", **contexto_dashboard())


@app.get("/jobs")
def vista_trabajos(request: Request, error: str | None = None, mensaje: str | None = None):
    return _render(
        request,
        "jobs.html",
        "jobs",
        trabajos=ledger.listar_trabajos(limite=100),
        fuentes=listar_fuentes(),
        fuente_defecto=_fuente_por_defecto(),
        error=error,
        mensaje=mensaje,
    )


@app.post("/jobs")
def nuevo_trabajo(
    fuente: str = Form(...),
    firebird_real: str | None = Form(None),
    permitir_borrador: str | None = Form(None),
    reset_esquema: str | None = Form(None),
):
    try:
        job_id = trabajos.iniciar_migracion(
            fuente,
            usar_firebird_real=bool(firebird_real),
            permitir_borrador=bool(permitir_borrador),
            reset_esquema=bool(reset_esquema),
        )
    except Exception as exc:
        return _volver("/jobs", error=f"{type(exc).__name__}: {exc}")
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


def _contexto_trabajo(job_id: str) -> dict[str, Any] | None:
    trabajo = ledger.obtener_trabajo(job_id)
    if trabajo is None:
        return None
    procesadas = trabajo["tablas_ok"] + trabajo["tablas_fail"]
    return {
        "trabajo": trabajo,
        "pasos": pasos_de(trabajo),
        "detalle": _detalle(trabajo),
        "corridas": sorted(ledger.listar_corridas(job_id=job_id, limite=500), key=lambda c: c["iniciado_en"]),
        "progreso_pct": _pct(procesadas, trabajo["tablas_total"]),
        "procesadas": procesadas,
        "comparacion": ledger.obtener_comparacion(trabajo["comparacion_id"]) if trabajo.get("comparacion_id") else None,
        "grafica": grafica_progreso(trabajo),
    }


@app.get("/jobs/{job_id}")
def vista_trabajo(request: Request, job_id: str):
    contexto = _contexto_trabajo(job_id)
    if contexto is None:
        return _render(request, "no_encontrado.html", "jobs", status_code=404, que=f"El trabajo de migración {job_id}")
    return _render(request, "job.html", "jobs", **contexto)


@app.get("/fragmento/jobs/{job_id}")
def fragmento_trabajo(request: Request, job_id: str):
    contexto = _contexto_trabajo(job_id)
    if contexto is None:
        return _render(request, "no_encontrado.html", "jobs", status_code=404, que=f"El trabajo de migración {job_id}")
    return _recargar_si_termino(request, contexto["trabajo"]["estado"] == "en_progreso") or _render(
        request, "_job.html", "jobs", **contexto
    )


@app.get("/data")
def vista_datos(request: Request, id: str | None = None, error: str | None = None, mensaje: str | None = None):
    from config_microsip.diferencial import leer_informe

    comparaciones = ledger.listar_comparaciones(limite=20)
    elegida = ledger.obtener_comparacion(id) if id else _ultima_comparacion_terminada()
    informe = leer_informe(elegida["comparacion_id"]) if elegida else None
    en_curso = any(c["estado"] == "en_progreso" for c in comparaciones)
    if recarga := _recargar_si_termino(request, en_curso):
        return recarga
    manifiestos = [cargar_manifiesto(f, t) for f in listar_fuentes() for t in listar_manifiestos(f)]
    return _render(
        request,
        "data.html",
        "data",
        comparaciones=comparaciones,
        elegida=elegida,
        informe=informe,
        dona=dona(elegida),
        tablas_manifiesto=len(manifiestos),
        columnas=sum(len(m.campos) for m in manifiestos),
        en_curso=en_curso,
        fuentes=listar_fuentes(),
        fuente_defecto=_fuente_por_defecto(),
        error=error,
        mensaje=mensaje,
    )


@app.post("/data/comparar")
def comparar(fuente: str = Form(...), firebird_real: str | None = Form(None)):
    try:
        trabajos.iniciar_comparacion(fuente, usar_firebird_real=bool(firebird_real))
    except Exception as exc:
        return _volver("/data", error=f"{type(exc).__name__}: {exc}")
    return _volver("/data", mensaje="Comparación diferencial iniciada: esta página se actualiza sola al terminar.")


@app.get("/tests")
def vista_pruebas(request: Request, error: str | None = None, mensaje: str | None = None):
    historial = ledger.listar_pruebas(limite=40)
    en_curso = any(p["estado"] == "en_progreso" for p in historial)
    if recarga := _recargar_si_termino(request, en_curso):
        return recarga
    ultimo = ultimo_resultado_por_suite()
    return _render(
        request,
        "tests.html",
        "tests",
        suites=SUITES,
        ultimo=ultimo,
        historial=historial,
        casos={s: _detalle(p).get("casos", []) for s, p in ultimo.items() if p},
        en_curso=en_curso,
        error=error,
        mensaje=mensaje,
    )


@app.post("/tests/run")
def correr_pruebas(suite: str = Form("all")):
    if suite != "all" and suite not in SUITES:
        return _volver("/tests", error=f"Suite desconocida: {suite}")
    suites = list(SUITES) if suite == "all" else [suite]
    if any(p["estado"] == "en_progreso" for p in ledger.listar_pruebas(limite=10)):
        return _volver("/tests", error="Ya hay pruebas en curso; espera a que terminen.")
    trabajos.iniciar_pruebas(suites)
    return _volver("/tests", mensaje=f"En ejecución: {', '.join(SUITES[s] for s in suites)}")


@app.get("/logs")
def vista_logs(request: Request):
    return _render(
        request, "logs.html", "logs", errores=errores_recientes(limite=200), actividad=ledger.actividad_reciente(limite=60)
    )


@app.get("/logs/export.csv")
def exportar_logs():
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["hora", "tabla", "error", "detalle", "enlace"])
    for e in errores_recientes(limite=1000):
        escritor.writerow([_fecha_hora(e["cuando"]), e["tabla"], e["tipo"], e["texto"], e["enlace"]])
    return StreamingResponse(
        iter([salida.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=errores-migracion.csv"},
    )


@app.get("/agent")
def vista_agente(request: Request):
    return _render(request, "agent.html", "agent", pendientes=pendientes_agente(), actividad=ledger.actividad_reciente(limite=10))


@app.get("/settings")
def vista_ajustes(request: Request):
    from config_microsip.config import ConfigPostgres
    from config_microsip.rutas import raiz_datos, ruta_ledger

    return _render(
        request,
        "settings.html",
        "settings",
        sistema=estado_sistema(forzar=True),
        postgres=ConfigPostgres.desde_entorno().descripcion_segura(),
        raiz_datos=str(raiz_datos()),
        ledger_ruta=str(ruta_ledger()),
    )


# --- tablas (manifiestos) y acciones por tabla -----------------------------------------


@app.get("/tables")
def vista_tablas(request: Request, error: str | None = None, mensaje: str | None = None):
    fuentes = []
    for fuente in listar_fuentes():
        tablas = []
        for tabla in listar_manifiestos(fuente):
            manifiesto = cargar_manifiesto(fuente, tabla)
            corridas = ledger.listar_corridas(fuente=fuente, tabla=tabla, limite=20)
            tablas.append(
                {
                    "tabla": tabla,
                    "manifiesto": manifiesto,
                    "grafo": describir_grafo(manifiesto),
                    "validacion": next((c for c in corridas if c["tipo"] == "validacion"), None),
                    "migracion": next((c for c in corridas if c["tipo"] == "migracion"), None),
                }
            )
        fuentes.append({"fuente": fuente, "tablas": tablas})
    return _render(request, "tables.html", "tables", fuentes=fuentes, error=error, mensaje=mensaje)


@app.get("/fuente/{fuente}")
def detalle_fuente(fuente: str):
    return RedirectResponse(url=f"/tables#{fuente}", status_code=307)


@app.post("/fuente/{fuente}/tabla/{tabla}/extraer")
def extraer(fuente: str, tabla: str, firebird_real: str | None = Form(None)):
    from config_microsip.orquestador import extraer_y_validar

    try:
        resultado = extraer_y_validar(fuente, tabla, usar_firebird_real=bool(firebird_real))
    except Exception as exc:
        return _volver("/tables", error=f"{tabla}: {type(exc).__name__}: {exc}")
    return RedirectResponse(url=f"/corrida/{resultado['run_id']}", status_code=303)


@app.post("/fuente/{fuente}/tabla/{tabla}/migrar")
def migrar(fuente: str, tabla: str, firebird_real: str | None = Form(None), permitir_borrador: str | None = Form(None)):
    from config_microsip.orquestador import migrar_a_postgres

    try:
        resultado = migrar_a_postgres(
            fuente, tabla, usar_firebird_real=bool(firebird_real), permitir_borrador=bool(permitir_borrador)
        )
    except Exception as exc:
        return _volver("/tables", error=f"{tabla}: {type(exc).__name__}: {exc}")
    return RedirectResponse(url=f"/corrida/{resultado['run_id']}", status_code=303)


@app.get("/corrida/{run_id}")
def detalle_corrida(request: Request, run_id: str):
    corrida = ledger.obtener_corrida(run_id)
    if corrida is None:
        return _render(request, "no_encontrado.html", "jobs", status_code=404, que=f"La corrida {run_id}")
    run_dir = ruta_runs() / corrida["fuente"] / corrida["tabla"] / run_id
    comparison = _leer_json(run_dir / "comparison.json")
    evidencia = sorted(p.name for p in (run_dir / "evidence").iterdir()) if (run_dir / "evidence").is_dir() else []
    candidato = next((a for a in evidencia if a.endswith("_candidato.csv")), None)
    muestra = None
    if candidato:
        with (run_dir / "evidence" / candidato).open(newline="", encoding="utf-8") as f:
            lector = csv.reader(f)
            muestra = {"encabezado": next(lector, []), "filas": [fila for _, fila in zip(range(8), lector, strict=False)]}
    return _render(
        request,
        "corrida.html",
        "jobs",
        corrida=corrida,
        detalle_error=_detalle(corrida),
        comparison=comparison,
        fallas=[v for v in (comparison or {}).get("verificaciones", []) if not v.get("ok")],
        queries=_leer_json(run_dir / "queries.json"),
        entrada_muestra=_leer_json(run_dir / "entrada_muestra.json") or [],
        salida_muestra=muestra,
        report_md=(run_dir / "report.md").read_text(encoding="utf-8") if (run_dir / "report.md").exists() else None,
        archivos_evidencia=evidencia,
        run_dir=str(run_dir),
    )


@app.get("/esquema")
def esquema(request: Request):
    from config_microsip.esquema import listar_tablas

    conexion = estado_sistema(forzar=True)["firebird"]
    tablas, error = [], conexion.get("error")
    if conexion.get("ok"):
        try:
            tablas = listar_tablas(con_conteo=True)
        except Exception as exc:
            error = str(exc)
    return _render(request, "esquema.html", "schema", conexion=conexion, tablas=tablas, error=error)


@app.get("/esquema/{tabla}")
def esquema_tabla(request: Request, tabla: str):
    from config_microsip.esquema import describir_tabla

    try:
        descripcion, error = describir_tabla(tabla), None
    except Exception as exc:
        descripcion, error = None, str(exc)
    return _render(request, "esquema_tabla.html", "schema", tabla=tabla, d=descripcion, error=error)
