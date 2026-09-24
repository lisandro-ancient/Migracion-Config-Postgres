# Changelog

Todos los cambios que se notan al usar el proyecto. Formato basado en
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones según
[SemVer](https://semver.org/lang/es/) con las reglas propias de docs/VERSIONADO.md.

Cada PR agrega su línea en **Sin publicar** (Agregado / Cambiado / Corregido / Eliminado). Al
publicar, `python ci/version.py subir patch|minor|major` convierte esa sección en la versión nueva.

## Sin publicar

_Nada todavía._

## 1.0.0 — 2026-09-23

Primera versión publicada. Lee la base CONFIG de MicroSIP en solo lectura, la valida contra el
propio origen y la migra a PostgreSQL, con evidencia verificable de cada paso.

### Agregado

- **Lectura de CONFIG en solo lectura** (Firebird 3/4/5, embebido o por red): transacción READ ONLY
  confirmada por el servidor; `verificar-conexion` comprueba además que la base sea CONFIG por su
  forma (EMPRESAS y USUARIOS con FK en cascada).
- **Manifiestos por tabla** generados del esquema real (`generar-manifiesto`), con motor de reglas,
  llaves compuestas, catálogos por FK y exclusión automática de columnas con credenciales.
- **Validación contra el origen**: conteo, llave única, nulos, integridad referencial, checksum y
  golden dataset, con evidencia en `runs/`.
- **Migración a PostgreSQL**: esquema derivado del manifiesto con las mismas reglas de borrado que
  CONFIG, carga espejo idempotente, verificación fila por fila y comparación diferencial.
- **Centro de control de migración** (panel web en español): KPIs, trabajos en segundo plano,
  comparación diferencial, pruebas, registros, agente y configuración.
- **Servidor MCP** (`config-microsip`, 18 herramientas) para operar todo desde un agente.
- **Pruebas** unitarias, de integración, diferenciales (incluida la CONFIG real) y de extremo a
  extremo (129).
- **CI/CD** en GitHub Actions contra Firebird 5 y PostgreSQL 16 reales (réplica de la estructura de
  CONFIG), con publicación de imagen en GHCR y releases por etiqueta; guía de instalación para
  macOS y Windows.
- **Versionado semántico** (docs/VERSIONADO.md): `ci/version.py` para cortar versiones, verificación
  de coherencia en la CI y aviso en PRs sin línea en el CHANGELOG. La versión se ve en la CLI
  (`--version`), el panel, el servidor MCP, la imagen y cada tabla migrada en PostgreSQL.
- **Evolución del esquema**: si una tabla de PostgreSQL quedó de una versión anterior del manifiesto,
  la migración se detiene y explica cómo recrearla (`--reset-esquema`).

## Desarrollo previo a 1.0.0 (no publicado)

Iteraciones internas del mismo día, antes de la primera versión. Se conservan como historial.

### 0.4.1 — 2026-09-23

- Guía de instalación y uso para **macOS y Windows** (`docs/INSTALACION.md`): requisitos, las dos
  formas de conectar en Windows (Firebird Server de MicroSIP o copia embebida), `.env` con rutas de
  Windows, `.mcp.json` para Windows, uso diario y problemas frecuentes.
- `scripts/ci_local.sh` funciona también en Windows (Git Bash / WSL 2): detecta `.venv\Scripts`, ya no
  depende de `nc` y busca el `fbclient.dll` habitual.
- `.gitattributes`: scripts y código siempre con finales de línea LF.

### 0.4.0 — 2026-09-23

- **Pipeline de CI/CD** en GitHub Actions: calidad (ruff, mypy, manifiestos/DDL/plantillas,
  actionlint), seguridad (pip-audit, bandit, gitleaks), unitarias en Python 3.11–3.13,
  integración, diferencial y e2e contra **Firebird 5 y PostgreSQL 16 reales**, cobertura combinada
  (mínimo 80%), construcción del paquete y de la imagen Docker (humo + Trivy), publicación en GHCR
  y release automática por etiqueta. Más Dependabot, plantilla de PR, pre-commit, verificación
  manual contra la CONFIG real (runner self-hosted) y `scripts/ci_local.sh` para reproducir la CI.
- **Réplica de CONFIG para CI**: estructura real generada de la CONFIG (`ci/config_replica.sql`) +
  datos inventados (`ci/datos_replica.sql`) + `ci/crear_replica.py` (solo crea bases nuevas).
- **Imagen Docker** del panel/CLI (`Dockerfile`), con cliente `libfbclient2`, usuario sin
  privilegios y healthcheck.
- **Python mínimo 3.11**: firebird-driver 2.x no instala en 3.10 (antes se declaraba 3.10+ por error).
- Correcciones encontradas por las nuevas etapas: un f-string inválido antes de Python 3.12,
  `zip(strict=True)` al emparejar columnas con valores, tipos opcionales sin verificar (mypy) y
  pytest actualizado a 9.0.3 (vulnerabilidad PYSEC-2026-1845).

### 0.3.1 — 2026-09-23

- Panel traducido por completo al español: navegación, vistas, estados, mensajes, pasos del
  trabajo, actividad, errores, nombres de las suites y encabezados del CSV exportado
  (`errores-migracion.csv`). Formato numérico es-MX (1,234.5).

### 0.3.0 — 2026-09-23

- **Nuevo panel "Migration Control Center"** con el diseño de
  `firebird_postgresql_migration_dashboard.html`: Dashboard, Migration Jobs, Data Overview, Tests &
  Validation, Logs & Errors, AI Agent, Settings, Tables y Live Schema. Todos los valores salen del
  ledger, la evidencia y las conexiones reales; sin contadores de demostración.
- **Trabajos de migración en segundo plano** (`trabajos.py`) con progreso en vivo (tabla y paso
  actual), un trabajo a la vez, y trabajos interrumpidos marcados al reiniciar el panel.
- **Comparación diferencial** Firebird ↔ PostgreSQL (`diferencial.py`, CLI vía MCP
  `comparar_diferencial`): coinciden / diferentes / faltantes / sobrantes / rechazadas y esquema;
  cada trabajo de migración termina con una.
- **Suites de pruebas** unit / integration / differential / e2e (marcadores de pytest, cada
  módulo clasificado en `conftest.py`) ejecutables desde el panel (`pruebas.py`).
- Pruebas nuevas: diferenciales (sintéticas + CONFIG real con oráculo independiente + reglas de
  borrado), integración de trabajos, ejecutor y panel, y end-to-end (panel real por HTTP + CLI).
  Total: 129.
- Ledger con tablas `trabajos`, `comparaciones` y `pruebas`; `corridas.job_id`. Los ledgers
  existentes se actualizan sin perder historial.

### 0.2.0 — 2026-09-23

- **Migración a PostgreSQL** (`migrar`, `migrar-todo`, `generar-ddl`, `consultar-postgres`,
  `verificar-postgres`; 4 herramientas MCP nuevas; botones en el dashboard). PostgreSQL 16 local en
  `docker-compose.yml`, puerto 5434.
- DDL derivado del manifiesto: PK, NOT NULL, CHECK de catálogos derivados y FK con la misma regla de
  borrado que CONFIG (`al_borrar`), diferibles.
- Carga espejo idempotente (upsert + borrado de lo ausente) en una transacción, solo tras pasar la
  validación contra el origen; verificación posterior en PostgreSQL fila por fila.
- Manifiestos en borrador bloqueados salvo `--permitir-borrador`. Ledger con columna `tipo`
  (`validacion` | `migracion`).
- CONFIG real migrado: 16 tablas, 11 FK (10 en cascada), todas las verificaciones en verde.

#### Antes de 0.2.0 (mismo día)

- Conectado al CONFIG.FDB real (16 tablas). `verificar-conexion` ahora diagnostica si la base es
  CONFIG por su forma (EMPRESAS y USUARIOS con FK en cascada), no por el nombre del archivo.
- Borradores de manifiesto para las 16 tablas, con snapshot capturado; todas validan OK en modo
  snapshot y en vivo.
- El generador declara cada FK real de una columna como catálogo `ref_<tabla>` validado por
  integridad referencial (11 FKs en CONFIG), y excluye columnas con credenciales
  (PASSWORD, TOKEN, REFRESH_TOKEN…) para que nunca terminen en un snapshot.
- La extracción materializa los BLOB de texto grandes que el driver entrega en streaming.

### 0.1.0 — 2026-09-23

Versión inicial, derivada de la arquitectura de `migracion-firebird-postgres-clientes` 1.0.0 sin
PostgreSQL: solo se conecta a la base CONFIG de Firebird, en modo de solo lectura.

- Conexión de solo lectura verificada por el servidor (`MON$READ_ONLY`), embebida o remota.
- Introspección del esquema real y generador de manifiestos borrador.
- Harness de Extracción + Harness de Testing en memoria (conteo, llave única, nulos,
  integridad referencial contra catálogos de CONFIG, checksum, golden).
- Llaves primarias compuestas.
- CLI, servidor MCP (13 herramientas) y dashboard con explorador de esquema en vivo.
