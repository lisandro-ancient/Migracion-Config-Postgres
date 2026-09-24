"""Validación estática del repositorio, sin bases de datos (etapa "calidad" de la CI):

- cada manifiesto de fuentes/*/manifiestos carga y pasa sus validaciones (Pydantic);
- su grafo de dependencias no tiene ciclos y cada snapshot que declara existe;
- el DDL de PostgreSQL de cada fuente se genera sin errores;
- cada golden, si existe, es JSON válido con la forma esperada;
- todas las plantillas del panel compilan (Jinja2).

    python ci/validar_manifiestos.py
"""

from __future__ import annotations

import json
import sys

from jinja2 import Environment, FileSystemLoader

from config_microsip.grafo import orden_de_extraccion
from config_microsip.harness_migracion import ddl_fuente
from config_microsip.manifiesto import cargar_manifiesto, listar_fuentes, listar_manifiestos, ruta_golden
from config_microsip.rutas import RUTA_PROYECTO


def main() -> int:
    errores: list[str] = []
    total = 0
    for fuente in listar_fuentes():
        for tabla in listar_manifiestos(fuente):
            total += 1
            try:
                m = cargar_manifiesto(fuente, tabla)
                orden_de_extraccion(m)
                if not m.ruta_fixture().exists():
                    errores.append(f"{fuente}/{tabla}: falta el snapshot {m.fixture}")
                for c in m.catalogos:
                    if c.tipo == "tabla" and not c.ruta_fixture().exists():
                        errores.append(f"{fuente}/{tabla}: falta el snapshot del catálogo {c.nombre} ({c.fixture})")
                golden = ruta_golden(fuente, tabla)
                if golden.exists():
                    casos = json.loads(golden.read_text(encoding="utf-8"))["casos"]
                    if not all("entrada" in c and "salida_esperada" in c for c in casos):
                        errores.append(f"{fuente}/{tabla}: golden con casos mal formados")
            except Exception as exc:
                errores.append(f"{fuente}/{tabla}: {type(exc).__name__}: {exc}")
        try:
            ddl_fuente(fuente)
        except Exception as exc:
            errores.append(f"{fuente}: el DDL de PostgreSQL no se pudo generar: {exc}")

    entorno = Environment(loader=FileSystemLoader(RUTA_PROYECTO / "dashboard" / "templates"), autoescape=True)
    entorno.filters.update({n: (lambda v, *a, **k: v) for n in ("hora", "fecha_hora", "duracion", "miles")})
    plantillas = entorno.list_templates()
    for nombre in plantillas:
        try:
            entorno.get_template(nombre)
        except Exception as exc:
            errores.append(f"plantilla {nombre}: {exc}")

    for e in errores:
        print(f"::error::{e}")
    print(f"{total} manifiestos y {len(plantillas)} plantillas revisados; {len(errores)} errores.")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
