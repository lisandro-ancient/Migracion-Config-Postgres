# Base CONFIG de MicroSIP — de Firebird a PostgreSQL, validada

**Versión `1.0.0`** · [`CHANGELOG.md`](CHANGELOG.md) · [cómo se versiona y se publica](docs/VERSIONADO.md)

## ¿Qué es esto?

Proyecto hermano de `migracion-firebird-postgres-clientes`,
con la misma arquitectura (manifiestos versionados, motor de reglas, harnesses, ledger, MCP,
dashboard), aplicado a la **base CONFIG** de MicroSIP: una base por instalación, hermana de las
bases de empresa, cuyo eje son `EMPRESAS` y `USUARIOS` — casi todo lo demás cuelga de ellas con
borrado en cascada.

Hace dos cosas, en este orden:

1. **Lee CONFIG con garantías** (solo lectura) y valida cada tabla contra el propio origen.
2. **La migra a PostgreSQL** — solo si la validación pasó — replicando llaves, nulos y **las mismas
   reglas de borrado en cascada**, y verifica fila por fila en PostgreSQL que quedó idéntica.

- **Nunca escribe en Firebird.** Cada lectura corre en una transacción `READ ONLY` que termina en
  `ROLLBACK`; el servidor lo confirma (`MON$READ_ONLY = 1`) y rechaza cualquier escritura.
- **Comprueba que la base sea CONFIG** por su forma (EMPRESAS y USUARIOS con FK en cascada), no por
  el nombre del archivo.
- **No supone la estructura de CONFIG.** La lee de las tablas de sistema y genera manifiestos
  *borrador* para revisión humana. Las columnas con credenciales (PASSWORD, TOKEN…) se excluyen solas.
- **La migración es un espejo idempotente**: upsert de lo que hay en el origen y borrado de lo que ya
  no está, en una sola transacción. Correrla dos veces deja lo mismo.

## Requisitos

- Python 3.11+ (probado con 3.11, 3.12 y 3.13; firebird-driver 2.x no admite 3.10).
- Docker Desktop (PostgreSQL local desechable, puerto **5434**).
- Un cliente de Firebird 3+ de 64 bits: el runtime embebido de Firebird 5 (macOS) o el Firebird
  que instaló MicroSIP (Windows).
- La base `CONFIG.FDB`: una copia, o la de MicroSIP a través de su Firebird Server.

## Instalación

**Guía paso a paso para macOS y Windows, con problemas frecuentes:
[`docs/INSTALACION.md`](docs/INSTALACION.md).** En resumen:

| | macOS (Terminal) | Windows (PowerShell) |
|---|---|---|
| Entorno | `python3.12 -m venv .venv` | `py -3.12 -m venv .venv` |
| Dependencias | `./.venv/bin/pip install -r requirements-dev.txt` | `.\.venv\Scripts\pip install -r requirements-dev.txt` |
| Paquete | `./.venv/bin/pip install -e . --no-deps` | `.\.venv\Scripts\pip install -e . --no-deps` |
| Configuración | `cp .env.example .env` y editarlo | `Copy-Item .env.example .env` y editarlo |
| PostgreSQL | `docker compose up -d` | `docker compose up -d` |
| Verificar | `./.venv/bin/python -m config_microsip.cli verificar-conexion` | `.\.venv\Scripts\python -m config_microsip.cli verificar-conexion` |
| Pruebas | `./.venv/bin/pytest -q` | `.\.venv\Scripts\pytest -q` |
| Panel | `./.venv/bin/uvicorn dashboard.app:app --port 8020` | `.\.venv\Scripts\uvicorn dashboard.app:app --port 8020` |

Los comandos de las secciones siguientes usan la forma de macOS; en Windows cambia `./.venv/bin/`
por `.\.venv\Scripts\`.

## Uso

```bash
# 1. Conexiones
./.venv/bin/python -m config_microsip.cli verificar-conexion   # Firebird: ok, solo lectura, es_base_config
./.venv/bin/python -m config_microsip.cli verificar-postgres   # PostgreSQL de destino

# 2. Conocer CONFIG y preparar manifiestos
./.venv/bin/python -m config_microsip.cli inspeccionar --con-conteo
./.venv/bin/python -m config_microsip.cli generar-manifiesto --tabla USUARIOS   # borrador en fuentes/config/manifiestos/
./.venv/bin/python -m config_microsip.cli capturar --tabla usuarios             # snapshot en fixtures/config/

# 3. Validar sin migrar
./.venv/bin/python -m config_microsip.cli extraer --tabla usuarios [--firebird-real] --vista-rica

# 4. Migrar a PostgreSQL
./.venv/bin/python -m config_microsip.cli generar-ddl --salida sql/config.sql      # revisar el esquema destino
./.venv/bin/python -m config_microsip.cli migrar-todo --firebird-real              # todas, padre -> hijo
./.venv/bin/python -m config_microsip.cli migrar --tabla usuarios --firebird-real  # una (sus padres ya migrados)
./.venv/bin/python -m config_microsip.cli consultar-postgres --tabla registry --id 4
```

- Sin `--firebird-real` se usa el último snapshot capturado; con él, la base en vivo.
- Un manifiesto en `estado: borrador` no se migra salvo con `--permitir-borrador`.
- `migrar-todo --reset-esquema` borra el esquema `config` **de PostgreSQL** antes de migrar.
- Cada corrida deja evidencia en `runs/config/<tabla>/<run_id>/` (`report.md`, `comparison.json`,
  `queries.json` con el DDL aplicado, `evidence/*.csv`).

### Panel — Centro de control de migración

```bash
./.venv/bin/uvicorn dashboard.app:app --port 8020
```

`http://127.0.0.1:8020/` — diseño basado en `firebird_postgresql_migration_dashboard.html`, con
**todos los números reales** (nada de contadores de demostración):

| Vista | Qué muestra / qué hace |
|---|---|
| **Panel** | KPIs (filas en Firebird, migradas y coincidentes, duración, errores, pendientes), progreso real del último trabajo, dona de la comparación diferencial, resultado de cada suite de pruebas, trabajo actual con sus pasos, actividad, errores e historial. Se actualiza cada 3 s. Botón **Ejecutar migración**. |
| **Trabajos de migración** | Historial de trabajos y **+ Nueva migración** (en segundo plano; el detalle muestra el avance tabla por tabla en vivo). |
| **Resumen de datos** | Comparación diferencial por tabla: coinciden / diferentes / faltantes / sobrantes / rechazadas y esquema; muestras de cada desviación. Botón **Ejecutar comparación diferencial**. |
| **Pruebas y validación** | **Ejecutar todas las pruebas** corre de verdad las suites unit / integration / differential / e2e y muestra cada caso. |
| **Registros y errores** | Corridas fallidas y desviaciones; **Exportar registros** (CSV). |
| **Agente IA** | Decisiones abiertas en los manifiestos (borradores, `CHAR(1)` sin dominio…) y cómo actuar vía MCP. Nada se aprueba solo. |
| **Configuración** | Conexiones reales (Firebird: solo lectura, ¿es CONFIG?; PostgreSQL) y política de migración. |
| **Tablas / Esquema en vivo** | Validar o migrar una tabla; explorar el esquema de CONFIG en vivo. |

Un solo trabajo pesado (migración o comparación) a la vez; si el panel se reinicia a mitad, lo
que estaba en curso se marca como interrumpido.

## Pruebas

```bash
./.venv/bin/pytest -q                  # todas (129)
./.venv/bin/pytest -q -m unit          # 54 · funciones puras, reglas, generador, configuración
./.venv/bin/pytest -q -m integration   # 47 · Firebird real, PostgreSQL, MCP, panel, trabajos
./.venv/bin/pytest -q -m differential  # 26 · origen ↔ PostgreSQL fila por fila (incluye CONFIG real)
./.venv/bin/pytest -q -m e2e           #  2 · panel real por HTTP + CLI real
```

- **Diferenciales** (`test_diferencial.py`): tras migrar, todo coincide; y el comparador detecta
  cada desviación introducida a propósito (valor, texto mal codificado, fila faltante/sobrante,
  columna ausente). Un oráculo escrito aparte del motor de reglas verifica PostgreSQL contra el
  snapshot crudo.
- **Diferencial de CONFIG real** (`test_diferencial_config.py`): una prueba por tabla que lee
  Firebird con SQL propio, calcula el valor esperado con su propio oráculo y lo compara con el
  esquema `config` de PostgreSQL; más una que verifica que las 11 FK tienen la misma regla de
  borrado en ambos lados. Se salta si CONFIG no está conectado o no se migró todavía.
- **End-to-end** (`test_e2e.py`): levanta el panel en un subproceso real, crea un trabajo por HTTP,
  sigue su progreso, verifica PostgreSQL, altera un dato por fuera, comprueba que la comparación y
  los logs lo detectan, y que volver a migrar lo repara; y la CLI de punta a punta.
- Las pruebas que escriben en PostgreSQL usan solo el esquema `prueba` (datos sintéticos de
  `tests/datos/`); nunca `config`. Cada módulo pertenece a una suite en `tests/conftest.py` — uno sin
  clasificar hace fallar la recolección.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`), en cada PR, en `main`, en etiquetas `v*` y cada día hábil:

```
calidad ─┬─ unitarias (3.11–3.13) ─┬─ integración ─┐
seguridad┘                         ├─ diferencial ─┼─ cobertura (≥80%) ─┐
                                   └─ e2e ─────────┘                    ├─ publicar imagen (GHCR) ─ release
                                      construcción (paquete + imagen) ──┘
```

Integración, diferencial, e2e y construcción corren contra un **Firebird 5 y un PostgreSQL 16
reales**; el Firebird tiene una **réplica de la estructura de CONFIG** (las 16 tablas y sus 11 FK)
con datos inventados, así que la extracción en vivo, la migración y el diferencial se prueban de
verdad sin que la CONFIG real salga de tu máquina. Detalle de cada etapa y cómo reproducirla en
local (`scripts/ci_local.sh`) en [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Como agente (MCP)

Copia `.mcp.json.example` a `.mcp.json` y ajusta las rutas a tu máquina (Windows: ver [`docs/INSTALACION.md`](docs/INSTALACION.md)); registra `config-microsip` (18 herramientas): exploración (`verificar_conexion`,
`listar_tablas_config`, `describir_tabla_config`), manifiestos (`generar_borrador_manifiesto`,
`capturar_snapshot`, `listar_manifiestos_tool`, `obtener_grafo_dependencias`,
`listar_entradas_crudas`, `previsualizar_registro`), validación (`extraer_y_validar_tabla`,
`obtener_ultima_corrida`), migración (`verificar_postgres`, `migrar_tabla_postgres`,
`migrar_todo_postgres`, `consultar_registro_postgres`, `comparar_diferencial`), y `iniciar_dashboard`, `correr_pruebas`.

## Cómo funciona

```
fuentes/config/manifiestos/<tabla>.yaml
        │
        ▼
Harness de Extracción   lee CONFIG (snapshot o en vivo, READ ONLY) y normaliza cada fila
        ▼
Harness de Testing      conteo vs COUNT(*), llave única, nulos, FK, checksum, golden
        │               ── si falla: se detiene, PostgreSQL no recibe nada ──
        ▼
Harness de Migración    DDL del manifiesto (PK, NOT NULL, CHECK, FK con la regla de borrado
        │               de CONFIG) → upsert + borrado espejo en una transacción
        ▼
Verificación en PG      conteo, fila por fila y columna por columna, huérfanos
        ▼
runs/<fuente>/<tabla>/<run_id>/  +  ledger (runs.db)  →  CLI · MCP · dashboard
```

Detalle y decisiones en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

## Estado actual (CONFIG.FDB real, 2026-09-23)

16 tablas, las 16 con manifiesto borrador y snapshot, validadas y migradas a PostgreSQL
(`config_microsip`, esquema `config`) con todas las verificaciones en verde. Las 11 FK de CONFIG
existen en PostgreSQL: 10 `ON DELETE CASCADE` y `USUARIOS.ROL_ID` sin cascada, igual que en el
origen. Solo `EMPRESAS` (1), `REGISTRY` (27) y `VERSIONES_DB` (23) tienen filas en esta copia.

Pendiente de decisión humana: revisar los borradores (sobre todo los `CHAR(1)` de USUARIOS —
`ESTATUS`, `TIPO`, `AUTORIZADOR`, `ACCESO_EMPRESAS`, `USAR_ROL`— y `REGISTRY.TIPO`) y pasarlos a
`vigente`.

## Estructura

```
├── .env.example · .mcp.json · docker-compose.yml · requirements.txt · pyproject.toml · CLAUDE.md
├── fuentes/config/manifiestos/   un YAML por tabla de CONFIG
├── fuentes/config/golden/        casos verificados a mano (opcional)
├── fixtures/config/              snapshots capturados de CONFIG
├── sql/config.sql                DDL PostgreSQL generado (para revisión; se aplica desde el manifiesto)
├── src/config_microsip/
│   ├── config.py · conexion.py        configuración y ÚNICA vía de conexión a Firebird (solo lectura)
│   ├── esquema.py · generador.py      introspección y borradores de manifiesto
│   ├── manifiesto.py · grafo.py · reglas/
│   ├── extract.py · harness_extraccion.py · harness_testing.py
│   ├── harness_migracion.py           DDL, carga espejo y verificación en PostgreSQL
│   ├── orquestador.py · ledger.py · display.py · cli.py · mcp_server.py
├── dashboard/                     FastAPI + Jinja2 + HTMX
├── tests/                         pytest; tests/datos/ es SINTÉTICO
└── docs/ARQUITECTURA.md
```

## Alcance y límites

- Carga completa por tabla (espejo), no replicación continua.
- Los tipos de PostgreSQL se derivan de la regla de cada columna (`TEXT`, `BIGINT`, `NUMERIC` sin
  precisión fija, `BOOLEAN`, `DATE`, `TIME`, `TIMESTAMP`); las longitudes VARCHAR de Firebird no se
  replican.
- Columnas BLOB binarias y con credenciales no se migran (quedan anotadas en cada borrador).
- Las pruebas de Firebird real y de PostgreSQL se saltan (no fallan) si esa base no está disponible.
