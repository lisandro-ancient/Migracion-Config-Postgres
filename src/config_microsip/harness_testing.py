"""Harness de Testing: compara el candidato contra la fuente de verdad —el
propio origen (conteo, checksum) y, cuando existe, un golden dataset
verificado a mano— y escribe la evidencia: report.md, comparison.json y
evidence/*.csv.

Solo evalúa y documenta; nunca modifica el candidato ni toca Firebird.
Todas las verificaciones trabajan en memoria sobre el ResultadoExtraccion.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .harness_extraccion import ResultadoExtraccion
from .manifiesto import Manifiesto


def validar_conteo(resultado: ResultadoExtraccion) -> dict[str, Any]:
    """Toda fila del origen debe terminar aceptada o rechazada (con motivo), y
    lo extraído debe coincidir con el COUNT(*) del origen — detecta un
    snapshot truncado o una extracción incompleta."""
    extraidas = len(resultado.filas_crudas)
    cuadra = extraidas == len(resultado.candidato) + len(resultado.rechazadas)
    coincide = resultado.conteo_origen is None or resultado.conteo_origen == extraidas
    return {
        "verificacion": "conteo_filas",
        "conteo_origen": resultado.conteo_origen,
        "filas_extraidas": extraidas,
        "filas_aceptadas": len(resultado.candidato),
        "filas_rechazadas": len(resultado.rechazadas),
        "nota": None
        if resultado.conteo_origen is not None
        else "el snapshot no registró conteo_origen; solo se verificó el cuadre interno",
        "ok": cuadra and coincide,
    }


def validar_llave_unica(manifiesto: Manifiesto, resultado: ResultadoExtraccion) -> dict[str, Any]:
    conteo = Counter(manifiesto.valor_llave(fila) for fila in resultado.candidato)
    duplicadas = sorted(k for k, n in conteo.items() if n > 1)
    return {
        "verificacion": "llave_primaria_unica",
        "llave": manifiesto.nombre_llave,
        "duplicadas": duplicadas[:50],
        "ok": not duplicadas,
    }


def validar_sin_nulos_en_obligatorios(manifiesto: Manifiesto, resultado: ResultadoExtraccion) -> dict[str, Any]:
    obligatorias = [c.destino for c in manifiesto.campos if not c.nulo_permitido]
    problemas = []
    for columna in obligatorias:
        nulos = sum(1 for fila in resultado.candidato if fila.get(columna) is None)
        if nulos:
            problemas.append({"columna": columna, "nulos": nulos})
    return {
        "verificacion": "sin_nulos_en_obligatorios",
        "columnas_revisadas": obligatorias,
        "problemas": problemas,
        "ok": not problemas,
    }


def validar_integridad_referencial(manifiesto: Manifiesto, resultado: ResultadoExtraccion) -> dict[str, Any]:
    """Cada valor no nulo de una columna con ``catalogo_fk`` debe existir en
    los ids de ese catálogo (extraído de la misma base CONFIG, o declarado)."""
    detalle = {}
    for campo in (c for c in manifiesto.campos if c.catalogo_fk):
        catalogo = manifiesto.catalogo(campo.catalogo_fk)
        columna_id = catalogo.columnas[0]
        ids = {str(f.get(columna_id)).strip() for f in resultado.catalogos.get(catalogo.nombre, [])}
        huerfanos = sorted(
            {
                str(fila[campo.destino])
                for fila in resultado.candidato
                if fila.get(campo.destino) is not None and str(fila[campo.destino]).strip() not in ids
            }
        )
        detalle[campo.destino] = {"catalogo": catalogo.nombre, "valores_sin_catalogo": huerfanos[:50], "total": len(huerfanos)}
    return {"verificacion": "integridad_referencial", "resultados": detalle, "ok": all(d["total"] == 0 for d in detalle.values())}


def validar_checksum(manifiesto: Manifiesto, resultado: ResultadoExtraccion) -> dict[str, Any] | None:
    """Suma del campo numérico declarado: origen (filas aceptadas, valor
    crudo) contra candidato (valor normalizado)."""
    if not manifiesto.campo_checksum:
        return None
    campo = next(c for c in manifiesto.campos if c.destino == manifiesto.campo_checksum)
    llaves_rechazadas = {r["llave"] for r in resultado.rechazadas}
    suma_origen = sum(
        (
            Decimal(str(f[campo.origen]))
            for f in resultado.filas_crudas
            if f.get(campo.origen) is not None and manifiesto.valor_llave_crudo(f) not in llaves_rechazadas
        ),
        Decimal("0"),
    )
    suma_candidato = sum((f[campo.destino] for f in resultado.candidato if f.get(campo.destino) is not None), Decimal("0"))
    return {
        "verificacion": f"checksum_{campo.destino}",
        "suma_origen": str(suma_origen),
        "suma_candidato": str(suma_candidato),
        "ok": suma_origen == suma_candidato,
    }


def _comparable(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def validar_contra_golden(manifiesto: Manifiesto, resultado: ResultadoExtraccion, golden: list[dict[str, Any]]) -> dict[str, Any]:
    """Cada caso del golden (verificado a mano, independiente del motor) contra
    la fila real del candidato: detecta un error en la regla misma."""
    por_llave = {manifiesto.valor_llave(f): f for f in resultado.candidato}
    diferencias = []
    for caso in golden:
        llave = manifiesto.valor_llave(caso["entrada"])
        real = por_llave.get(llave)
        if real is None:
            diferencias.append(f"{manifiesto.nombre_llave}={llave}: falta en el candidato")
            continue
        for campo, esperado in caso["salida_esperada"].items():
            if _comparable(real.get(campo)) != _comparable(esperado):
                diferencias.append(
                    f"{manifiesto.nombre_llave}={llave}, columna={campo}: esperado={esperado!r} != candidato={_comparable(real.get(campo))!r}"
                )
    return {"verificacion": "golden_dataset", "casos_verificados": len(golden), "diferencias": diferencias, "ok": not diferencias}


@dataclass
class ReporteHarnessTesting:
    ok_general: bool
    modo: str
    verificaciones: list[dict[str, Any]]
    filas_extraidas: int
    filas_aceptadas: int
    filas_rechazadas: int
    golden_disponible: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def ejecutar_todas_las_validaciones(
    manifiesto: Manifiesto, resultado: ResultadoExtraccion, golden: list[dict[str, Any]] | None = None
) -> ReporteHarnessTesting:
    verificaciones = [
        validar_conteo(resultado),
        validar_llave_unica(manifiesto, resultado),
        validar_sin_nulos_en_obligatorios(manifiesto, resultado),
        validar_integridad_referencial(manifiesto, resultado),
    ]
    checksum = validar_checksum(manifiesto, resultado)
    if checksum:
        verificaciones.append(checksum)
    if golden:
        verificaciones.append(validar_contra_golden(manifiesto, resultado, golden))
    return ReporteHarnessTesting(
        ok_general=all(v["ok"] for v in verificaciones),
        modo=resultado.modo,
        verificaciones=verificaciones,
        filas_extraidas=len(resultado.filas_crudas),
        filas_aceptadas=len(resultado.candidato),
        filas_rechazadas=len(resultado.rechazadas),
        golden_disponible=bool(golden),
    )


def _escribir_report_md(ruta: Path, manifiesto: Manifiesto, reporte: ReporteHarnessTesting, rechazadas: list[dict]) -> None:
    lineas = [
        f"# Reporte de extracción — {manifiesto.fuente}.{manifiesto.tabla_origen} → {manifiesto.tabla_destino}",
        "",
        f"**Resultado general:** {'✅ OK' if reporte.ok_general else '❌ FAIL'}  ·  modo: `{reporte.modo}`",
        "",
        f"- Filas extraídas: {reporte.filas_extraidas}",
        f"- Filas aceptadas: {reporte.filas_aceptadas}",
        f"- Filas rechazadas: {reporte.filas_rechazadas}",
        f"- Golden dataset: {'sí' if reporte.golden_disponible else 'no hay (solo verificaciones contra el origen)'}",
        "",
        "## Verificaciones",
        "",
        "| Verificación | Resultado | Detalle |",
        "|---|---|---|",
    ]
    for v in reporte.verificaciones:
        detalle = {k: val for k, val in v.items() if k not in ("verificacion", "ok")}
        lineas.append(f"| {v['verificacion']} | {'✅' if v['ok'] else '❌'} | {detalle} |")
    if rechazadas:
        lineas += ["", "## Filas rechazadas", ""] + [f"- `{f}`" for f in rechazadas]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _escribir_csv(ruta: Path, columnas: list[str], filas: list[dict[str, Any]]) -> None:
    with ruta.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        escritor.writerows([["" if fila.get(c) is None else fila.get(c) for c in columnas] for fila in filas])


def generar_evidencia(
    run_dir: Path, manifiesto: Manifiesto, reporte: ReporteHarnessTesting, resultado: ResultadoExtraccion
) -> dict[str, Any]:
    """Escribe report.md, comparison.json y evidence/ (candidato + rechazadas)
    en run_dir. comparison.json es la fuente de verdad del resultado."""
    evidencia = run_dir / "evidence"
    evidencia.mkdir(parents=True, exist_ok=True)
    comparison = reporte.to_dict()
    comparison["filas_rechazadas_en_transformacion"] = resultado.rechazadas
    (run_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    _escribir_report_md(run_dir / "report.md", manifiesto, reporte, resultado.rechazadas)
    _escribir_csv(
        evidencia / f"{manifiesto.tabla_destino}_candidato.csv", [c.destino for c in manifiesto.campos], resultado.candidato
    )
    if resultado.rechazadas:
        _escribir_csv(evidencia / f"{manifiesto.tabla_destino}_rechazadas.csv", ["llave", "motivo"], resultado.rechazadas)
    return comparison
