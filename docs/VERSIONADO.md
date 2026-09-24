# Versionado y publicación

El proyecto arranca en **1.0.0** y evoluciona con [versionado semántico](https://semver.org/lang/es/)
(`MAYOR.MENOR.PARCHE`). La versión vive en tres lugares que **siempre** deben coincidir —
`pyproject.toml`, `src/config_microsip/__init__.py` y su sección en `CHANGELOG.md`— y nadie los
edita a mano: lo hace `ci/version.py`, y la CI rechaza cualquier desajuste.

## Qué sube cada número

Lo que otros usan de este proyecto: la CLI, las herramientas MCP, el formato de los manifiestos,
el esquema que se crea en PostgreSQL, las variables de `.env` y las URLs del panel.

| Sube… | Cuando el cambio… | Ejemplos |
|---|---|---|
| **MAYOR** (`2.0.0`) | rompe algo de lo anterior: quien actualice tiene que cambiar su forma de usarlo | renombrar o quitar un comando de la CLI, una opción o una herramienta MCP; cambiar el formato de los manifiestos de forma incompatible (un campo nuevo obligatorio, una regla renombrada); cambiar cómo se nombran o tipan **todas** las tablas en PostgreSQL; renombrar una variable de `.env`; subir la versión mínima de Python |
| **MENOR** (`1.1.0`) | agrega algo sin romper lo existente | un comando, opción o herramienta MCP nueva; una regla de normalización nueva; un campo **opcional** nuevo en los manifiestos; una página nueva del panel; un manifiesto nuevo (una tabla más en PostgreSQL); **cambiar las columnas de un manifiesto existente** (ver abajo) |
| **PARCHE** (`1.0.1`) | corrige sin agregar ni romper | un error de validación o de carga; un texto del panel; documentación; una actualización de dependencias por seguridad |

**Cambios de manifiesto.** Si una versión agrega, quita o cambia el tipo de una columna de una
tabla ya migrada, la tabla existente en PostgreSQL queda desactualizada. La migración lo detecta y
se detiene con un mensaje que dice qué columnas difieren y cómo resolverlo. PostgreSQL es un destino
**derivado** de CONFIG, así que resolverlo es recrear el esquema:

```bash
python -m config_microsip.cli migrar-todo --firebird-real --reset-esquema
```

La línea del CHANGELOG de ese cambio debe decirlo: **“requiere `--reset-esquema`”**.

## En cada PR

Agrega una línea en la sección **`## Sin publicar`** de `CHANGELOG.md`, bajo la categoría que
corresponda:

```markdown
## Sin publicar

### Agregado
- Comando `exportar-csv` para descargar una tabla migrada.

### Corregido
- `USUARIOS.ESTATUS` se normalizaba sin recortar espacios.
```

Categorías: **Agregado**, **Cambiado**, **Corregido**, **Eliminado**, **Seguridad**. La CI avisa en
el PR si cambias código, manifiestos o dependencias sin tocar el CHANGELOG, y si alguien cambia el
número de versión a mano.

## Publicar una versión

1. Decide el número según la tabla de arriba, mirando lo que hay en “Sin publicar”.
2. Córtala (en una rama, como cualquier cambio):

   ```bash
   python ci/version.py subir minor --simular   # ver qué número saldría, sin escribir nada
   python ci/version.py subir minor             # patch | minor | major
   ```

   Esto actualiza `pyproject.toml` y `__init__.py`, convierte “Sin publicar” en `## 1.1.0 — <fecha>`
   y deja un “Sin publicar” vacío arriba. Se niega si no hay cambios pendientes.
3. PR con ese cambio → revisión → merge a `main`.
4. Etiqueta el commit de `main` y súbela:

   ```bash
   git checkout main && git pull
   git tag -a v1.1.0 -m "Versión 1.1.0"
   git push origin v1.1.0
   ```

5. La CI hace el resto: vuelve a correr todas las etapas, verifica que la etiqueta coincida con
   `pyproject.toml`, `__init__.py` y el CHANGELOG, publica la imagen
   `ghcr.io/microsip/firebird-config-microsip` con las etiquetas `1.1.0`, `1.1` y `latest`, y crea la
   release de GitHub con el paquete y las notas de esa sección del CHANGELOG.

Si una etiqueta no coincide con la versión del código, la release no se publica.

## Primera publicación: 1.0.0

El código ya está en 1.0.0. Para publicarlo por primera vez (una sola vez):

```bash
cd ~/dev/firebird-config-microsip
git add . && git commit -m "Versión 1.0.0"
git remote add origin git@github.com:Microsip/firebird-config-microsip.git
git push -u origin main
git tag -a v1.0.0 -m "Versión 1.0.0"
git push origin v1.0.0
```

Lo que aparece en el CHANGELOG bajo “Desarrollo previo a 1.0.0” fueron iteraciones internas que
nunca se publicaron; se conservan como historial.

## Dónde se ve la versión

| Lugar | Cómo |
|---|---|
| CLI | `python -m config_microsip.cli --version` |
| Panel | barra lateral (“Versión 1.0.0”) y **Configuración** |
| Agente (MCP) | el servidor `config-microsip` se anuncia con esa versión |
| PostgreSQL | cada tabla migrada lleva el comentario `config.EMPRESAS — config-microsip 1.0.0` (`\dt+ config.*` en psql) |
| Imagen Docker | etiquetas `1.0.0`, `1.0`, `latest` en GHCR |
| Paquete | `pip show firebird-config-microsip` |

## Actualizar una instalación a una versión nueva

1. Lee en el CHANGELOG las secciones entre tu versión y la nueva; busca **“requiere `--reset-esquema`”**.
2. Actualiza el código (`git pull` o `git checkout v1.1.0`) y las dependencias
   (`pip install -r requirements-dev.txt`), o usa la imagen nueva.
3. Si alguna versión intermedia lo pide, recrea el destino: `migrar-todo --firebird-real --reset-esquema`.
   Si se te pasa, la migración te lo recordará.
4. El registro local (`runs.db`) se actualiza solo y conserva su historial.

## Correcciones sobre una versión anterior

Normalmente solo se mantiene la última versión. Si hace falta corregir una anterior (por ejemplo,
1.0 cuando `main` ya va en 1.2): rama `release/1.0` desde la etiqueta `v1.0.0`, la corrección con
su línea en el CHANGELOG, `python ci/version.py subir patch` → `1.0.1`, y la etiqueta `v1.0.1` sobre
esa rama. La CI publica la imagen `1.0.1` (y `1.0`) **sin mover `latest`**: `latest` solo se mueve
cuando el commit etiquetado está en `main`.
