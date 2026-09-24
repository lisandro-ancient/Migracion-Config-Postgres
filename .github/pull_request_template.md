## Qué cambia y por qué

<!-- Una o dos oraciones. Si toca un manifiesto, di qué tabla y qué regla. -->

## Tipo de cambio

- [ ] Manifiesto / regla de normalización (`fuentes/`)
- [ ] Código de migración o validación (`src/`)
- [ ] Panel (`dashboard/`)
- [ ] Pruebas, CI o documentación

## Lista de verificación

- [ ] `scripts/ci_local.sh` pasa en mi máquina (o, al menos, `pytest -q` y `ruff check`)
- [ ] Nada escribe en Firebird: toda lectura pasa por `conexion_solo_lectura()`
- [ ] Si cambié un manifiesto: lo revisé contra el esquema real (`inspeccionar --tabla …`) y no incluye columnas con credenciales
- [ ] Si cambié la estructura esperada de CONFIG: regeneré `ci/config_replica.sql` (`python ci/generar_ddl_replica.py`)
- [ ] Pruebas nuevas registradas en `tests/conftest.py::SUITE_POR_MODULO`
- [ ] Texto del panel en español; `CHANGELOG.md` actualizado si el cambio se nota al usar el proyecto
