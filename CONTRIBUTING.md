# Cómo contribuir

## Antes de abrir un PR

Instalación en macOS o Windows: [`docs/INSTALACION.md`](docs/INSTALACION.md).

```bash
pip install -r requirements-dev.txt && pip install -e . --no-deps
pre-commit install          # lint, formato, tipos y manifiestos antes de cada commit
scripts/ci_local.sh         # la CI completa en tu máquina (~2–3 min, necesita Docker)
```

`scripts/ci_local.sh` levanta los mismos servicios que GitHub Actions —un Firebird 5 con la
réplica de CONFIG y una base PostgreSQL aparte (`config_ci`)— y **no toca** tu CONFIG.FDB, tu
`.env` ni el esquema `config` de tu PostgreSQL. Se puede correr por etapas:
`scripts/ci_local.sh calidad|seguridad|pruebas|construccion`.

## La réplica de CONFIG que usa la CI

La CONFIG real nunca sale de tu máquina. La CI usa:

- `ci/config_replica.sql`: la **estructura** real (16 tablas, tipos, llaves primarias y las 11
  llaves foráneas con su regla de borrado), generada de la CONFIG real con
  `python ci/generar_ddl_replica.py > ci/config_replica.sql`. **Regenérala si cambia la
  estructura de CONFIG** (por ejemplo, una versión nueva de MicroSIP).
- `ci/datos_replica.sql`: filas **inventadas** que cubren acentos, cascadas, autorreferencias y
  columnas con credenciales.
- `ci/crear_replica.py`: la crea en el Firebird del job. Es lo único del repositorio que escribe
  en Firebird, y solo puede **crear** una base nueva en un servidor remoto (falla si ya existe y se
  niega a correr en modo embebido).

## Etapas del pipeline (`.github/workflows/ci.yml`)

| # | Etapa | Qué verifica | Falla si… |
|---|---|---|---|
| 1 | **Calidad** | ruff (lint + formato), mypy, manifiestos/DDL/plantillas (`ci/validar_manifiestos.py`), actionlint, archivos prohibidos, clasificación de pruebas | cualquier error de estilo, tipos, un manifiesto inválido, un `.env`/`.fdb`/`runs.db` versionado |
| 2 | **Seguridad** | pip-audit (dependencias), bandit (código), gitleaks (secretos en todo el historial) | una vulnerabilidad conocida, un patrón inseguro nuevo, un secreto |
| 3 | **Unitarias** | `pytest -m unit` en Python 3.11, 3.12 y 3.13 | una prueba falla en cualquier versión |
| 4 | **Integración** | `pytest -m integration` con Firebird 5 y PostgreSQL 16 reales (réplica de CONFIG) | conexión, solo lectura, MCP, panel, trabajos… |
| 5 | **Diferencial** | migra la réplica **en vivo** y corre `pytest -m differential`: fila por fila, columna por columna, y las reglas de borrado en ambos lados | cualquier diferencia entre Firebird y PostgreSQL |
| 6 | **Extremo a extremo** | `pytest -m e2e` (panel real por HTTP + CLI) y humo de todas las vistas contra la réplica | una vista no responde o el flujo completo falla |
| 7 | **Cobertura** | combina la cobertura de 3–6 | baja de 80% |
| 8 | **Construcción** | paquete (sdist + wheel, `twine check --strict`), imagen Docker, humo de la imagen contra Firebird y PostgreSQL, Trivy | el paquete o la imagen no se construyen, o la imagen tiene vulnerabilidades HIGH/CRITICAL corregibles |
| 9 | **Publicar imagen** (CD) | solo en `main` y etiquetas `v*`: imagen en `ghcr.io/microsip/firebird-config-microsip` con SBOM y procedencia | — |
| 10 | **Release** (CD) | solo en etiquetas `v*`: verifica que la etiqueta = `pyproject.toml` = `__version__` = sección de `CHANGELOG.md`, y crea la release con el paquete | versiones incoherentes |
| — | **CHANGELOG** (solo PRs, avisa) | que un cambio visible agregue su línea en “Sin publicar” y que nadie cambie la versión a mano | nunca bloquea: deja un aviso en el PR |

Además: **Dependabot** abre cada lunes PRs de dependencias (pip, Actions, Docker), la CI corre
**cada día hábil** (06:00, México) para detectar roturas por dependencias, y
**`config-real.yml`** (manual, runner self-hosted) valida y migra la CONFIG real.

## Versiones

El proyecto usa versionado semántico a partir de **1.0.0**. Resumen (detalle en
[`docs/VERSIONADO.md`](docs/VERSIONADO.md)):

- **En cada PR:** una línea en `## Sin publicar` de `CHANGELOG.md` (Agregado / Cambiado / Corregido /
  Eliminado / Seguridad). Si cambias las columnas de un manifiesto, di “requiere `--reset-esquema`”.
- **Nunca** edites el número de versión a mano.
- **Publicar:** `python ci/version.py subir patch|minor|major` → PR → merge → `git tag -a vX.Y.Z` en
  `main` → `git push origin vX.Y.Z`. La CI verifica la versión, publica la imagen y crea la release.

## Convenciones

- Código, comentarios, documentación y texto del panel en **español**.
- Nada escribe en Firebird: toda lectura pasa por `conexion_solo_lectura()`.
- Toda prueba nueva va en `tests/conftest.py::SUITE_POR_MODULO` (si no, la recolección falla).
- Las pruebas que escriben en PostgreSQL usan el esquema `prueba`, nunca `config`.
