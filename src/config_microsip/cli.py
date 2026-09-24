"""CLI de config_microsip. Todo es de solo lectura contra Firebird.

Esquema real (requiere FIREBIRD_DATABASE):
    python -m config_microsip.cli verificar-conexion
    python -m config_microsip.cli inspeccionar [--tabla EMPRESAS] [--con-conteo]
    python -m config_microsip.cli generar-manifiesto --tabla EMPRESAS [--sobrescribir]
    python -m config_microsip.cli capturar --tabla empresas

Migración a PostgreSQL (docker compose up -d):
    python -m config_microsip.cli verificar-postgres
    python -m config_microsip.cli generar-ddl [--salida sql/config.sql]
    python -m config_microsip.cli migrar-todo [--firebird-real] [--permitir-borrador] [--reset-esquema]
    python -m config_microsip.cli migrar --tabla empresas [--firebird-real] [--permitir-borrador]
    python -m config_microsip.cli consultar-postgres --tabla empresas --id 1

Manifiestos (por defecto sobre el snapshot; --firebird-real para leer en vivo):
    python -m config_microsip.cli listar
    python -m config_microsip.cli extraer --tabla empresas [--firebird-real] [--vista-rica]
    python -m config_microsip.cli mostrar-entradas --tabla empresas --limite 10
    python -m config_microsip.cli comparar --tabla empresas --id 1

--fuente es 'config' por defecto.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .manifiesto import cargar_manifiesto, listar_fuentes, listar_manifiestos, ruta_manifiesto

FUENTE_POR_DEFECTO = "config"


def _json(datos) -> None:
    print(json.dumps(datos, indent=2, ensure_ascii=False, default=str))


def _filas(manifiesto, firebird_real: bool):
    if firebird_real:
        from .extract import extraer_desde_firebird

        return extraer_desde_firebird(manifiesto)[0]
    from .extract import extraer_filas_desde_fixture

    return extraer_filas_desde_fixture(manifiesto)


def _cmd_verificar(args) -> int:
    from .conexion import verificar_conexion

    resultado = verificar_conexion()
    _json(resultado)
    if resultado.get("ok") and not resultado.get("es_base_config"):
        print(f"\n⚠ {resultado.get('motivo')}", file=sys.stderr)
    return 0 if resultado.get("ok") and resultado.get("transaccion_solo_lectura") and resultado.get("es_base_config") else 1


def _cmd_inspeccionar(args) -> int:
    from .display import console, tabla_descripcion, tabla_listado_tablas
    from .esquema import describir_tabla, listar_tablas

    if args.tabla:
        descripcion = describir_tabla(args.tabla)
        _json(descripcion) if args.json else console.print(tabla_descripcion(descripcion))
    else:
        tablas = listar_tablas(con_conteo=args.con_conteo)
        _json(tablas) if args.json else console.print(tabla_listado_tablas(tablas))
    return 0


def _cmd_generar(args) -> int:
    from .esquema import describir_tabla, valores_distintos
    from .generador import generar_borrador

    descripcion = describir_tabla(args.tabla)
    destino = ruta_manifiesto(args.fuente, descripcion["tabla"].lower())
    if destino.exists() and not args.sobrescribir:
        print(f"Ya existe {destino}; usa --sobrescribir para reemplazarlo.", file=sys.stderr)
        return 1
    texto = generar_borrador(
        descripcion,
        fuente=args.fuente,
        valores_char1=None if args.sin_datos else (lambda col: valores_distintos(descripcion["tabla"], col)),
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Borrador escrito en {destino}", file=sys.stderr)
    return 0


def _cmd_capturar(args) -> int:
    from .extract import capturar_fixtures

    _json(capturar_fixtures(cargar_manifiesto(args.fuente, args.tabla)))
    return 0


def _cmd_listar(args) -> int:
    for fuente in listar_fuentes():
        print(f"{fuente}:")
        tablas = listar_manifiestos(fuente)
        for tabla in tablas:
            print(f"  - {tabla} ({cargar_manifiesto(fuente, tabla).estado})")
        if not tablas:
            print("  (sin manifiestos — ver 'generar-manifiesto')")
    return 0


def _cmd_extraer(args) -> int:
    from .orquestador import extraer_y_validar

    reporte = extraer_y_validar(args.fuente, args.tabla, usar_firebird_real=args.firebird_real)
    texto = json.dumps(reporte, indent=2, ensure_ascii=False, default=str)
    print(texto)
    if args.reporte:
        args.reporte.parent.mkdir(parents=True, exist_ok=True)
        args.reporte.write_text(texto, encoding="utf-8")
    if args.vista_rica:
        from .display import console, tabla_reporte_validacion

        console.print(tabla_reporte_validacion(reporte))
    return 0 if reporte["ok_general"] else 1


def _cmd_mostrar(args) -> int:
    from .display import console, tabla_entradas_crudas

    manifiesto = cargar_manifiesto(args.fuente, args.tabla)
    console.print(tabla_entradas_crudas(manifiesto, _filas(manifiesto, args.firebird_real), limite=args.limite))
    return 0


def _cmd_comparar(args) -> int:
    from .display import console, panel_comparacion_entrada_salida

    manifiesto = cargar_manifiesto(args.fuente, args.tabla)
    fila = next((f for f in _filas(manifiesto, args.firebird_real) if manifiesto.valor_llave_crudo(f) == str(args.id)), None)
    if fila is None:
        print(f"{manifiesto.nombre_llave}={args.id} no existe en el origen.", file=sys.stderr)
        return 1
    console.print(panel_comparacion_entrada_salida(manifiesto, fila))
    return 0


def _cmd_verificar_postgres(args) -> int:
    from .harness_migracion import verificar_postgres

    resultado = verificar_postgres()
    _json(resultado)
    return 0 if resultado["ok"] else 1


def _cmd_generar_ddl(args) -> int:
    from .harness_migracion import ddl_fuente

    texto = ddl_fuente(args.fuente)
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(texto, encoding="utf-8")
        print(f"DDL escrito en {args.salida}", file=sys.stderr)
    else:
        print(texto)
    return 0


def _cmd_migrar(args) -> int:
    from .orquestador import migrar_a_postgres

    reporte = migrar_a_postgres(
        args.fuente, args.tabla, usar_firebird_real=args.firebird_real, permitir_borrador=args.permitir_borrador
    )
    print(json.dumps(reporte, indent=2, ensure_ascii=False, default=str))
    if args.vista_rica:
        from .display import console, tabla_reporte_validacion

        console.print(tabla_reporte_validacion(reporte))
    return 0 if reporte["ok_general"] else 1


def _cmd_migrar_todo(args) -> int:
    from .orquestador import migrar_todo

    resultado = migrar_todo(
        args.fuente,
        usar_firebird_real=args.firebird_real,
        permitir_borrador=args.permitir_borrador,
        reset_esquema=args.reset_esquema,
    )
    from .display import console, tabla_migracion_todo

    console.print(tabla_migracion_todo(resultado))
    return 0 if resultado["ok_general"] else 1


def _cmd_consultar_postgres(args) -> int:
    from .harness_migracion import consultar_registro

    fila = consultar_registro(cargar_manifiesto(args.fuente, args.tabla), args.id)
    if fila is None:
        print(f"{args.id} no está en PostgreSQL (¿no se ha migrado, o se rechazó?).", file=sys.stderr)
        return 1
    _json(fila)
    return 0


def main(argv=None) -> int:
    from . import __version__

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"config-microsip {__version__}")
    subs = parser.add_subparsers(dest="comando", required=True)

    def sub(nombre, ayuda, funcion, *, fuente=True, tabla=None, firebird=False):
        p = subs.add_parser(nombre, help=ayuda)
        if fuente:
            p.add_argument("--fuente", default=FUENTE_POR_DEFECTO)
        if tabla is not None:
            p.add_argument("--tabla", required=tabla)
        if firebird:
            p.add_argument("--firebird-real", action="store_true", help="Leer la base CONFIG en vivo en vez del snapshot")
        p.set_defaults(func=funcion)
        return p

    sub("verificar-conexion", "Conecta, confirma solo lectura y muestra datos de la base", _cmd_verificar, fuente=False)
    p = sub("inspeccionar", "Lista las tablas de la base o describe una", _cmd_inspeccionar, fuente=False, tabla=False)
    p.add_argument("--con-conteo", action="store_true", help="Incluir COUNT(*) de cada tabla")
    p.add_argument("--json", action="store_true")
    p = sub("generar-manifiesto", "Escribe un manifiesto BORRADOR desde el esquema real", _cmd_generar, tabla=True)
    p.add_argument("--sobrescribir", action="store_true")
    p.add_argument("--sin-datos", action="store_true", help="No leer datos (valores CHAR(1)); solo el esquema")
    sub("capturar", "Guarda el snapshot de la tabla y sus catálogos (solo lectura)", _cmd_capturar, tabla=True)
    sub("listar", "Lista fuentes y manifiestos", _cmd_listar)
    p = sub("extraer", "Harness de Extracción + Harness de Testing para un manifiesto", _cmd_extraer, tabla=True, firebird=True)
    p.add_argument("--reporte", type=lambda s: Path(s).resolve(), default=None, help="Guardar el reporte JSON aquí")
    p.add_argument("--vista-rica", action="store_true")
    p = sub("mostrar-entradas", "Primeras N filas crudas", _cmd_mostrar, tabla=True, firebird=True)
    p.add_argument("--limite", type=int, default=10)
    p = sub("comparar", "Antes/después de un registro (llave compuesta: 'a|b')", _cmd_comparar, tabla=True, firebird=True)
    p.add_argument("--id", required=True)

    sub("verificar-postgres", "Conecta al PostgreSQL de destino", _cmd_verificar_postgres, fuente=False)
    p = sub("generar-ddl", "Imprime (o guarda) el DDL PostgreSQL de todos los manifiestos de la fuente", _cmd_generar_ddl)
    p.add_argument("--salida", type=lambda s: Path(s).resolve(), default=None)
    for nombre, ayuda, funcion, con_tabla in (
        ("migrar", "Extraer + validar + cargar una tabla a PostgreSQL + verificar", _cmd_migrar, True),
        ("migrar-todo", "Migra todas las tablas de la fuente en orden padre -> hijo", _cmd_migrar_todo, False),
    ):
        p = sub(nombre, ayuda, funcion, tabla=True if con_tabla else None, firebird=True)
        p.add_argument("--permitir-borrador", action="store_true", help="Migrar aunque el manifiesto siga en 'borrador'")
        if con_tabla:
            p.add_argument("--vista-rica", action="store_true")
        else:
            p.add_argument("--reset-esquema", action="store_true", help="DROP SCHEMA del destino en PostgreSQL antes de migrar")
    p = sub("consultar-postgres", "Un registro ya migrado, leído de PostgreSQL", _cmd_consultar_postgres, tabla=True)
    p.add_argument("--id", required=True)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
