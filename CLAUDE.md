# CLAUDE.md

## Qué es

Lee la base CONFIG de Firebird MicroSIP (una por instalación; eje EMPRESAS y USUARIOS con FK en
cascada) en **solo lectura**, la valida contra el propio origen y, solo si pasa, la migra a
PostgreSQL (`docker compose up -d`, puerto 5434) replicando las reglas de borrado. Misma
arquitectura que el proyecto hermano `migracion-firebird-postgres-clientes`.

## Comandos

```bash
./.venv/bin/pytest -q                                   # pruebas (las de Firebird/PostgreSQL se saltan si no están)
./.venv/bin/pytest -q -m unit|integration|differential|e2e   # una suite (ver tests/conftest.py::SUITE_POR_MODULO)
./.venv/bin/python -m config_microsip.cli verificar-conexion
./.venv/bin/python -m config_microsip.cli inspeccionar [--tabla X]
./.venv/bin/python -m config_microsip.cli generar-manifiesto --tabla X
./.venv/bin/python -m config_microsip.cli capturar --tabla x
./.venv/bin/python -m config_microsip.cli extraer --tabla x [--firebird-real]
./.venv/bin/python -m config_microsip.cli verificar-postgres
./.venv/bin/python -m config_microsip.cli migrar-todo [--firebird-real] [--permitir-borrador]
./.venv/bin/python -m config_microsip.cli migrar --tabla x [--firebird-real]
./.venv/bin/uvicorn dashboard.app:app --port 8020
```

## Reglas de trabajo

- **Nunca escribir en Firebird.** Toda conexión pasa por `conexion.conexion_solo_lectura()`; no
  agregar otra forma de conectar. Tampoco usar el MCP `firebird` (que sí escribe) para modificar CONFIG.
- **No suponer la estructura de CONFIG.** Describirla con `inspeccionar` / `describir_tabla_config`
  antes de escribir o corregir un manifiesto.
- **Golden a mano.** Nunca generar `fuentes/*/golden/*.json` corriendo el propio motor.
- Sin `ORDER BY` ni `DISTINCT` sobre tablas de datos (charset ISO8859_1 sin INTL); ordenar en Python.
- Todo identificador interpolado en SQL pasa por `identificador_seguro()`; los valores, como parámetros.
- PostgreSQL solo recibe candidatos que ya pasaron la validación contra el origen; no saltarse ese
  orden en `orquestador.migrar_a_postgres`. Las pruebas de PostgreSQL usan el esquema `prueba`, nunca `config`.
- `tests/datos/` es sintético; no describe CONFIG.
- Todo módulo de prueba nuevo se registra en `SUITE_POR_MODULO` (tests/conftest.py); si no, la
  recolección falla. `test_diferencial_config.py` debe seguir usando su propio oráculo, no el motor.
- El panel solo muestra datos reales (ledger, runs/, conexiones); no agregar valores de demostración.
  Todo el texto de interfaz va en español (plantillas y textos que arma Python: pasos, actividad, errores).
- La CI (ver CONTRIBUTING.md) corre con una réplica de la estructura de CONFIG; si cambia la
  estructura real, regenerar `ci/config_replica.sql` con `ci/generar_ddl_replica.py`.
  `scripts/ci_local.sh` reproduce la CI completa sin tocar la CONFIG ni el esquema `config`.
- Versionado semántico desde 1.0.0 (docs/VERSIONADO.md): cada cambio visible agrega su línea en
  `## Sin publicar` del CHANGELOG; el número solo lo cambia `python ci/version.py subir …`. Cambiar las
  columnas de un manifiesto es MENOR y su línea debe decir “requiere `--reset-esquema`”.
- Documentación, comentarios y mensajes de commit en español.
