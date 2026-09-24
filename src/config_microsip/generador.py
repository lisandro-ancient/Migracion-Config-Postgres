"""Generador de *borradores* de manifiesto a partir del esquema real.

La estructura de la base CONFIG no se supone: se lee con esquema.describir_tabla
y se traduce a un manifiesto YAML con ``estado: borrador``. El borrador es un
punto de partida para revisión humana, no una decisión:

- Tipo de columna -> regla de normalización, con una tabla fija y explicable
  (``REGLA_POR_CATEGORIA``).
- Columnas CHAR(1) cuyos valores observados son solo S/N se proponen como
  ``bandera_sn``; el resto queda como ``texto`` con los valores observados en
  un comentario, para que alguien decida si son un catálogo.
- Las llaves foráneas reales del origen se anotan en comentarios; declarar el
  catálogo correspondiente es una decisión de alcance que toma quien revise.
- BLOB binario y tipos sin regla quedan fuera, anotados.

Nunca genera golden: un golden producido por el mismo código que valida no
detectaría nada (lección L-golden del proyecto hermano).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

# Columnas con credenciales: nunca entran a un manifiesto, porque capturar el
# snapshot las escribiría en fixtures/ dentro del repositorio.
_SENSIBLE = re.compile(r"(PASSWORD|PASSWD|CONTRASE|TOKEN|SECRET|API_?KEY)", re.IGNORECASE)

REGLA_POR_CATEGORIA = {
    "entero": "entero",
    "decimal": "decimal_con_signo",  # sin suponer que no hay negativos
    "texto": "texto",
    "blob_texto": "texto",
    "fecha": "fecha",
    "hora": "hora",
    "timestamp": "timestamp",
    "booleano": "booleano",
}


def _yaml_str(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def proponer_campo(
    columna: dict[str, Any], valores_observados: list[Any] | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """(campo propuesto o None si se excluye, comentarios para el YAML)."""
    categoria = columna["categoria"]
    notas: list[str] = []
    if _SENSIBLE.search(columna["nombre"]):
        return None, [f"{columna['nombre']}: excluida — contiene credenciales; no debe terminar en un snapshot"]
    regla = REGLA_POR_CATEGORIA.get(categoria)
    if regla is None:
        return None, [f"{columna['nombre']} ({columna['tipo']}): excluida — sin regla para la categoría '{categoria}'"]

    nulo_permitido = columna["nulo_permitido"]
    if categoria == "texto" and columna.get("longitud") == 1 and valores_observados is not None:
        no_nulos = {str(v).strip().upper() for v in valores_observados if v is not None}
        if no_nulos and no_nulos <= {"S", "N"}:
            regla = "bandera_sn"
            notas.append(
                f"{columna['nombre']}: valores observados {sorted(no_nulos)} -> bandera_sn (confirmar que es un sí/no de negocio)"
            )
        else:
            muestra = sorted({str(v) for v in valores_observados})[:15]
            notas.append(f"{columna['nombre']}: CHAR(1) con valores observados {muestra} — ¿catálogo derivado?")
        if any(v is None for v in valores_observados) and not nulo_permitido:
            notas.append(f"{columna['nombre']}: el esquema dice NOT NULL pero se observaron NULL")

    campo = {
        "origen": columna["nombre"],
        "destino": columna["nombre"].lower(),
        "regla": regla,
        "nulo_permitido": nulo_permitido,
    }
    return campo, notas


def generar_borrador(
    descripcion: dict[str, Any],
    *,
    fuente: str,
    valores_char1: Callable[[str], list[Any]] | None = None,
) -> str:
    """Texto YAML del borrador. ``valores_char1(columna)`` devuelve los valores
    observados de una columna CHAR(1) (None = no consultar datos)."""
    tabla = descripcion["tabla"]
    tabla_destino = tabla.lower()
    llave = [c.lower() for c in descripcion["llave_primaria"]]
    campos, notas = [], []
    for columna in descripcion["columnas"]:
        observados = None
        if valores_char1 and columna["categoria"] == "texto" and columna.get("longitud") == 1:
            observados = valores_char1(columna["nombre"])
        campo, notas_col = proponer_campo(columna, observados)
        notas += notas_col
        if campo:
            campos.append(campo)

    if not llave:
        notas.insert(0, "La tabla NO tiene llave primaria declarada: se propuso la primera columna; revisar.")
        llave = [campos[0]["destino"]] if campos else []
    destinos = {c["destino"] for c in campos}
    for k in llave:
        if k not in destinos:
            notas.append(f"La columna de llave '{k}' quedó excluida; el manifiesto no será válido hasta resolverlo.")

    # Cada FK real de una sola columna se declara como catálogo tipo 'tabla'
    # (prefijo ref_ para no chocar con la tabla principal en autorreferencias,
    # p. ej. USUARIOS.ROL_ID -> USUARIOS) y se valida con catalogo_fk.
    por_columna: dict[str, list[dict]] = {}
    for fk in descripcion.get("llaves_foraneas", []):
        por_columna.setdefault(fk["restriccion"], []).append(fk)
    catalogos: list[dict[str, Any]] = []
    fk_de_campo: dict[str, str] = {}
    for segmentos in por_columna.values():
        fk = segmentos[0]
        if len(segmentos) > 1:
            notas.append(f"FK compuesta {fk['restriccion']} -> {fk['tabla_referida']}: no se valida automáticamente")
            continue
        if fk["columna"].lower() not in destinos:
            continue
        nombre = f"ref_{fk['tabla_referida'].lower()}"
        fk_de_campo[fk["columna"].lower()] = nombre
        if nombre not in {c["nombre"] for c in catalogos}:
            columna_ref = fk["columna_referida"]
            catalogos.append(
                {
                    "nombre": nombre,
                    "tabla_origen": fk["tabla_referida"],
                    "columna": columna_ref,
                    "fixture": f"fixtures/{fuente}/{nombre}_raw_snapshot.json",
                    "al_borrar": fk.get("al_borrar", "restrict"),
                }
            )
        notas.append(
            f"FK real en origen: {fk['columna']} -> {fk['tabla_referida']}.{fk['columna_referida']} (validada vía catálogo {nombre})"
        )

    lineas = [
        f"# BORRADOR generado desde el esquema real de {tabla} (config_microsip.generador).",
        "# Revisar cada regla antes de pasar a 'estado: vigente'. Nada aquí es una decisión de negocio verificada.",
        f"# Filas en origen al generar: {descripcion.get('filas')}",
        "#",
    ]
    lineas += [f"# - {n}" for n in notas] or ["# (sin observaciones)"]
    lineas += [
        "",
        f"fuente: {fuente}",
        "estado: borrador",
        f"tabla_origen: {tabla}",
        f"tabla_destino: {tabla_destino}",
        f"llave_primaria: {llave[0] if len(llave) == 1 else '[' + ', '.join(llave) + ']'}",
        f"fixture: fixtures/{fuente}/{tabla_destino}_raw_snapshot.json",
        f"depende_de: [{', '.join(c['nombre'] for c in catalogos)}]",
    ]
    if catalogos:
        lineas.append("catalogos:")
        for c in catalogos:
            lineas += [
                f"  - nombre: {c['nombre']}",
                "    tipo: tabla",
                f"    tabla_origen: {c['tabla_origen']}",
                f"    fixture: {c['fixture']}",
                f"    columnas: [{c['columna'].lower()}]",
                f"    mapeo_columnas: [[{_yaml_str(c['columna'])}, {c['columna'].lower()}]]",
                f"    al_borrar: {c['al_borrar']}",
            ]
    else:
        lineas.append("catalogos: []")
    lineas += ["", "campos:"]
    for c in campos:
        fk = f", catalogo_fk: {fk_de_campo[c['destino']]}" if c["destino"] in fk_de_campo else ""
        lineas.append(
            f"  - {{origen: {_yaml_str(c['origen'])}, destino: {c['destino']}, regla: {c['regla']}, "
            f"nulo_permitido: {'true' if c['nulo_permitido'] else 'false'}{fk}}}"
        )
    return "\n".join(lineas) + "\n"
