# Arquitectura

## Punto de partida

`migracion-firebird-postgres-clientes` resolvió "migrar una tabla de MicroSIP" con piezas que no
dependen de PostgreSQL: manifiesto declarativo, motor de reglas, grafo de dependencias, harness que
construye un candidato, harness que lo compara y deja evidencia, ledger, y tres interfaces (CLI, MCP,
dashboard). Este proyecto conserva todas esas piezas, las aplica a la base CONFIG y separa dos fases:

1. **Validación contra el origen, en memoria.** El candidato es el conjunto de filas normalizadas;
   el Harness de Testing lo compara contra CONFIG (conteo, llave, nulos, FK, checksum, golden) sin
   necesitar ningún destino. Esta fase sola ya es útil (`extraer`).
2. **Migración a PostgreSQL, solo si la fase 1 pasó** (`migrar` / `migrar-todo`): el Harness de
   Migración crea el esquema desde el manifiesto, carga el candidato como espejo y verifica en
   PostgreSQL. Si la validación contra el origen falla, PostgreSQL no recibe nada.

La única base Firebird es CONFIG, y solo se lee: toda conexión pasa por
`conexion.conexion_solo_lectura()`. No existe otra forma de abrir Firebird en el código.

## Migración a PostgreSQL

| Decisión | Por qué |
|---|---|
| DDL generado del manifiesto (no escrito a mano por tabla) | Con 16 tablas, un DDL a mano por tabla duplicaría el manifiesto y podría divergir. El manifiesto revisado es la fuente única; `generar-ddl` lo deja en `sql/config.sql` para revisión y cada corrida guarda el DDL aplicado en `queries.json`. |
| Un esquema de PostgreSQL por fuente (`config`) | Aísla la migración; `--reset-esquema` solo toca ese esquema. Las pruebas usan el esquema `prueba`. |
| FK con la **misma regla de borrado** que CONFIG (`al_borrar` del catálogo, leído de `RDB$REF_CONSTRAINTS`) | El comportamiento de negocio de CONFIG —borrar una empresa o un usuario arrastra su configuración— debe seguir valiendo en el destino. |
| FK `DEFERRABLE INITIALLY DEFERRED`; RESTRICT de Firebird → `NO ACTION` | Permite cargar autorreferencias (`USUARIOS.ROL_ID`) en una transacción; `NO ACTION` diferido tiene el mismo efecto que RESTRICT al confirmar. |
| Carga espejo: upsert + borrado de lo ausente, en una transacción | Idempotente y fiel al origen: una fila borrada en CONFIG desaparece en PostgreSQL (con sus cascadas, igual que en CONFIG). Cualquier error revierte la tabla completa. |
| Orden padre → hijo entre manifiestos (`orden_de_migracion`) | Las FK exigen que la tabla padre exista; `migrar` de una tabla hija sin su padre falla con un mensaje claro. |
| Verificación leyendo PostgreSQL, fila por fila y columna por columna | Detecta cualquier pérdida por tipo o conversión, no solo un conteo distinto. |
| Tipos: `NUMERIC` sin precisión, `BIGINT`, `TEXT` | Conservan exactamente el valor de origen; las longitudes VARCHAR no aportan garantías que el motor de reglas no dé ya. |
| Borradores bloqueados por defecto (`--permitir-borrador`) | Un manifiesto sin revisión humana no debería alimentar un destino sin que alguien lo decida explícitamente. |

## Decisiones

| Decisión | Por qué |
|---|---|
| Transacción `READ COMMITTED RECORD_VERSION` + `READ ONLY`, siempre `ROLLBACK` | El servidor rechaza cualquier escritura aunque haya un bug; `verificar_conexion` lo confirma con `MON$TRANSACTIONS.MON$READ_ONLY`. Read committed record-version no espera locks de otras sesiones de MicroSIP. |
| Conexión efímera por operación | CONFIG la comparten todas las empresas y usuarios; no retener un attachment mientras el proceso está inactivo (mismo criterio que `~/mcp-firebird`). |
| Charset `NONE` + decodificación ISO8859_1 en Python | El runtime embebido local no trae el módulo INTL de ISO8859_1: `charset=ISO8859_1` falla al conectar, y con `NONE` el driver decodifica como UTF-8 y revienta con la primera "ó". Fijar la codificación de la conexión antes de abrir cursores resuelve ambas cosas y recupera filas que el proyecto hermano tenía que rechazar (su CLIENTES 3771). |
| Sin `ORDER BY`/`DISTINCT` en tablas de datos | Construir una clave de orden sobre columnas ISO8859_1 sin INTL falla en el servidor. Orden y distintos se calculan en Python. |
| `COUNT(*)` y filas en la misma transacción | El conteo de origen y lo extraído son la misma foto; un desfase indica extracción o snapshot incompletos, no una escritura concurrente. |
| Manifiestos *borrador* generados del esquema | La estructura de CONFIG no se supone. El generador traduce tipos a reglas con una tabla fija y deja anotadas las dudas (CHAR(1) no S/N, FKs reales, columnas excluidas) para que decida una persona. |
| Golden siempre a mano | Un golden producido por el motor que valida no detecta errores del motor. El generador nunca lo escribe. |
| Decimal sin redondeo | CONFIG puede guardar tasas o porcentajes con más de dos decimales; el proyecto hermano redondeaba a 0.01 porque sus montos eran de crédito. |
| Llaves primarias compuestas | Tablas de relación (p. ej. derechos por usuario) no tienen una sola columna llave; el valor de llave se representa como `a|b`. |
| Catálogos `tabla` | La integridad referencial se valida contra otra tabla de la misma base CONFIG, extraída igual que la principal (snapshot o en vivo). |
| Raíz de datos configurable (`CONFIG_MICROSIP_DATOS`) | Las pruebas trabajan sobre una copia temporal; se puede apuntar a otra carpeta de manifiestos sin tocar código. |
| Cambio de cwd permanente al runtime embebido | El motor carga ICU con rutas relativas al cwd. Restaurarlo tras cada conexión sería una carrera entre hilos del dashboard; todo el proyecto usa rutas absolutas. |

## Verificaciones del Harness de Testing

| Verificación | Falla cuando |
|---|---|
| `conteo_filas` | extraídas ≠ `COUNT(*)` del origen, o extraídas ≠ aceptadas + rechazadas |
| `llave_primaria_unica` | dos filas del candidato comparten llave |
| `sin_nulos_en_obligatorios` | una columna con `nulo_permitido: false` quedó en NULL |
| `integridad_referencial` | un valor con `catalogo_fk` no existe en los ids del catálogo |
| `checksum_<campo>` | la suma del campo en origen (filas aceptadas) ≠ la del candidato |
| `golden_dataset` | un caso verificado a mano no coincide con el candidato |

Una fila **rechazada** por el motor (dato que no cumple su regla) no es un fallo de validación: queda
excluida con su motivo en `comparison.json` y `evidence/<tabla>_rechazadas.csv`.

## Qué no es

- No es una migración ni una sincronización: no escribe en ningún lado salvo la evidencia local.
- No hay un loop autónomo de agente: "el agente" es quien usa el MCP, lee `comparison.json` y
  corrige el manifiesto.
