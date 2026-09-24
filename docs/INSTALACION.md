# Instalación y uso en macOS y Windows

Guía paso a paso para dejar el proyecto funcionando en una máquina nueva. Los pasos son los
mismos en los dos sistemas; cambian los comandos y dónde vive Firebird.

- [Requisitos](#requisitos)
- [macOS](#macos)
- [Windows](#windows)
- [Uso diario (ambos sistemas)](#uso-diario-ambos-sistemas)
- [Problemas frecuentes](#problemas-frecuentes)

---

## Requisitos

| Qué | macOS | Windows |
|---|---|---|
| **Python 3.11 o más reciente** (3.10 no sirve: firebird-driver 2.x lo exige) | `brew install python@3.12` o [python.org](https://www.python.org/downloads/) | [python.org](https://www.python.org/downloads/): marca **“Add python.exe to PATH”** |
| **Git** | viene con las Command Line Tools (`xcode-select --install`) | [Git for Windows](https://git-scm.com/download/win) (incluye Git Bash) |
| **Docker Desktop** (el PostgreSQL de destino) | [docker.com](https://www.docker.com/products/docker-desktop/) | [docker.com](https://www.docker.com/products/docker-desktop/), con el motor WSL 2 |
| **Cliente de Firebird 3, 4 o 5** (64 bits) | runtime de Firebird 5 (ver abajo) | el Firebird que ya instaló MicroSIP, o el de [firebirdsql.org](https://firebirdsql.org/en/firebird-5-0/) |
| **La base CONFIG.FDB** | una **copia** | la de la instalación de MicroSIP, o una copia |

> **Qué es CONFIG.FDB.** Una base por instalación de MicroSIP, hermana de las bases de empresa
> (en Windows suele estar en `C:\Microsip datos\CONFIG.FDB`). Su eje son `EMPRESAS` y `USUARIOS`.
> El proyecto **nunca escribe en ella**: cada lectura es una transacción de solo lectura que el
> propio servidor confirma, y `verificar-conexion` comprueba que la base conectada sea de verdad
> CONFIG (no una base de empresa).

---

## macOS

### 1. Clonar e instalar

```bash
git clone git@github.com:Microsip/firebird-config-microsip.git ~/dev/firebird-config-microsip
cd ~/dev/firebird-config-microsip
python3.12 -m venv .venv                       # o python3 si ya es 3.11+
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pip install -e . --no-deps
```

### 2. Firebird (modo embebido: sin servidor)

En macOS no hace falta un Firebird Server: el proyecto abre la copia de CONFIG.FDB directamente
con el **motor embebido** de Firebird 5. Necesitas dos rutas:

- **Si ya tienes `~/mcp-firebird`** (el MCP de Firebird del equipo), usa su runtime:
  - biblioteca: `~/mcp-firebird/firebird-runtime/Libraries/libfbclient.dylib`
  - runtime: `~/mcp-firebird/firebird-runtime/Resources`
- **Si no**, instala el paquete de Firebird 5 para macOS de
  [firebirdsql.org](https://firebirdsql.org/en/firebird-5-0/). Queda como framework, típicamente en:
  - biblioteca: `/Library/Frameworks/Firebird.framework/Versions/A/Libraries/libfbclient.dylib`
  - runtime: `/Library/Frameworks/Firebird.framework/Resources`

### 3. Copiar CONFIG.FDB

Tráela de la máquina donde corre MicroSIP (cópiala **con MicroSIP cerrado**) y ponla **fuera** de
Escritorio, Documentos y Descargas: macOS protege esas carpetas y puede bloquear el acceso.

```bash
mkdir -p ~/dev/bases
cp ~/Downloads/CONFIG.FDB ~/dev/bases/CONFIG.FDB
```

### 4. Configurar `.env`

```bash
cp .env.example .env
open -e .env
```

Deja estas líneas (con tus rutas y la contraseña de SYSDBA):

```ini
FIREBIRD_DATABASE=/Users/<tu-usuario>/dev/bases/CONFIG.FDB
FIREBIRD_USER=SYSDBA
FIREBIRD_PASSWORD=<contraseña>
FIREBIRD_HOST=
FIREBIRD_CLIENT_LIBRARY=/Users/<tu-usuario>/mcp-firebird/firebird-runtime/Libraries/libfbclient.dylib
FIREBIRD_RUNTIME_DIR=/Users/<tu-usuario>/mcp-firebird/firebird-runtime/Resources
FIREBIRD_CHARSET=
```

### 5. PostgreSQL y verificación

```bash
docker compose up -d
./.venv/bin/python -m config_microsip.cli verificar-conexion   # "ok": true, "es_base_config": true
./.venv/bin/python -m config_microsip.cli verificar-postgres   # "ok": true
./.venv/bin/pytest -q                                          # todas las pruebas
```

Sigue en [Uso diario](#uso-diario-ambos-sistemas). En macOS los comandos empiezan con
`./.venv/bin/`.

---

## Windows

Todos los comandos son de **PowerShell** (no hace falta “activar” el entorno virtual: se llama
directo a `.venv\Scripts\...`, así no choca con la política de ejecución de scripts).

### 1. Clonar e instalar

```powershell
git clone git@github.com:Microsip/firebird-config-microsip.git $HOME\dev\firebird-config-microsip
cd $HOME\dev\firebird-config-microsip
py -3.12 -m venv .venv                          # o: python -m venv .venv (si es 3.11+)
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\pip install -e . --no-deps
```

### 2. Firebird: elige una de dos formas

**A. A través del Firebird Server de MicroSIP (recomendado si trabajas en la máquina de MicroSIP).**
MicroSIP ya tiene un Firebird Server corriendo, así que te conectas por red a `localhost` y lees la
CONFIG real en vivo, en solo lectura (no hace falta copiarla).

- `FIREBIRD_HOST=localhost`
- `FIREBIRD_DATABASE` = la ruta **tal como la ve el servidor**, p. ej. `C:\Microsip datos\CONFIG.FDB`
- `FIREBIRD_CLIENT_LIBRARY` = el `fbclient.dll` de esa instalación, p. ej.
  `C:\Program Files\Firebird\Firebird_5_0\fbclient.dll` (en Firebird 3 o 4, la carpeta `Firebird_3_0`
  o `Firebird_4_0`)

> El cliente debe ser Firebird **3 o más reciente** (firebird-driver no funciona con el cliente de
> Firebird 2.5). Si `verificar-conexion` muestra la versión del motor, estás bien.

**B. Una copia, en modo embebido (sin servidor).** Para trabajar con una copia sin tocar el
servidor: descarga el **zip** de Firebird 5 x64 de
[firebirdsql.org](https://firebirdsql.org/en/firebird-5-0/), descomprímelo en `C:\firebird5` y copia
`CONFIG.FDB` a `C:\bases\CONFIG.FDB`.

- `FIREBIRD_HOST=` (vacío = embebido)
- `FIREBIRD_DATABASE=C:\bases\CONFIG.FDB`
- `FIREBIRD_CLIENT_LIBRARY=C:\firebird5\fbclient.dll`
- `FIREBIRD_RUNTIME_DIR=C:\firebird5`

### 3. Configurar `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Ejemplo para la forma **A**. Pon las rutas de Windows entre **comillas simples**: con comillas
dobles, una secuencia como `\t` o `\n` dentro de la ruta se convierte en tabulador o salto de línea.
También sirven barras normales: `C:/Microsip datos/CONFIG.FDB`.

```ini
FIREBIRD_HOST=localhost
FIREBIRD_PORT=3050
FIREBIRD_DATABASE='C:\Microsip datos\CONFIG.FDB'
FIREBIRD_USER=SYSDBA
FIREBIRD_PASSWORD=<contraseña>
FIREBIRD_CLIENT_LIBRARY='C:\Program Files\Firebird\Firebird_5_0\fbclient.dll'
FIREBIRD_RUNTIME_DIR=
FIREBIRD_CHARSET=
```

### 4. PostgreSQL y verificación

Abre Docker Desktop y espera a que diga *Engine running*.

```powershell
docker compose up -d
.\.venv\Scripts\python -m config_microsip.cli verificar-conexion   # "ok": true, "es_base_config": true
.\.venv\Scripts\python -m config_microsip.cli verificar-postgres   # "ok": true
.\.venv\Scripts\pytest -q
```

### 5. Usarlo como agente en Claude Code (opcional)

Copia `.mcp.json.example` a `.mcp.json` (no se versiona: tiene rutas de tu máquina) y pon las tuyas. En Windows queda así (en JSON las `\` se escriben dobles):

```json
{
  "mcpServers": {
    "config-microsip": {
      "type": "stdio",
      "command": "C:\\Users\\<tu-usuario>\\dev\\firebird-config-microsip\\.venv\\Scripts\\python.exe",
      "args": ["-m", "config_microsip.mcp_server"],
      "cwd": "C:\\Users\\<tu-usuario>\\dev\\firebird-config-microsip",
      "env": { "PYTHONPATH": "C:\\Users\\<tu-usuario>\\dev\\firebird-config-microsip\\src" }
    }
  }
}
```

Sigue en [Uso diario](#uso-diario-ambos-sistemas). En Windows los comandos empiezan con
`.\.venv\Scripts\`.

---

## Uso diario (ambos sistemas)

Los comandos se muestran en su forma de macOS. En Windows, cambia `./.venv/bin/` por `.\.venv\Scripts\`.

| Para… | Comando |
|---|---|
| Arrancar PostgreSQL (tras reiniciar la máquina) | `docker compose up -d` |
| Ver las tablas de CONFIG | `./.venv/bin/python -m config_microsip.cli inspeccionar --con-conteo` |
| Validar una tabla | `./.venv/bin/python -m config_microsip.cli extraer --tabla usuarios --firebird-real --vista-rica` |
| Migrar todo a PostgreSQL | `./.venv/bin/python -m config_microsip.cli migrar-todo --firebird-real --permitir-borrador` |
| Consultar un registro migrado | `./.venv/bin/python -m config_microsip.cli consultar-postgres --tabla registry --id 4` |
| **Abrir el panel** | `./.venv/bin/uvicorn dashboard.app:app --port 8020` → http://127.0.0.1:8020 |
| Correr las pruebas | `./.venv/bin/pytest -q` (o una suite: `-m unit`, `-m integration`, `-m differential`, `-m e2e`) |
| Revisiones antes de cada commit | `./.venv/bin/pre-commit install` (una vez) |
| **La CI completa en local** | macOS: `scripts/ci_local.sh` · Windows: `bash scripts/ci_local.sh` en **Git Bash** o **WSL 2** |

Detener el panel: `Ctrl+C` en su terminal. Detener PostgreSQL: `docker compose down`
(los datos se conservan en un volumen; `docker compose down -v` los borra).

> `scripts/ci_local.sh` levanta su propio Firebird 5 en Docker con una réplica de CONFIG y usa una
> base PostgreSQL aparte (`config_ci`): no toca tu CONFIG.FDB, tu `.env` ni el esquema `config`.
> En Windows necesita un cliente de Firebird: busca `C:\Program Files\Firebird\Firebird_5_0\fbclient.dll`
> o usa el que indiques en `FIREBIRD_CLIENT_LIBRARY`.

---

## Problemas frecuentes

| Mensaje o síntoma | Causa | Solución |
|---|---|---|
| `FIREBIRD_DATABASE no está definida` | falta `.env` o la variable | `cp .env.example .env` (Windows: `Copy-Item`) y complétalo |
| `"es_base_config": false` | la ruta apunta a una base de **empresa** (p. ej. `APPCO.FDB`) | apunta a `CONFIG.FDB`, en la misma carpeta que las bases de empresa |
| `CHARACTER SET ISO8859_1 is not defined` | el runtime no trae ese juego de caracteres | deja `FIREBIRD_CHARSET=` vacío (el proyecto decodifica en Python) |
| `Could not find acceptable ICU library` (macOS) | falta el runtime del motor embebido | revisa `FIREBIRD_RUNTIME_DIR` |
| `Could not find fbclient` / `%1 is not a valid Win32 application` (Windows) | ruta equivocada o cliente de 32 bits con Python de 64 | usa el `fbclient.dll` **x64** y pon su ruta completa en `FIREBIRD_CLIENT_LIBRARY` |
| `Your user name and password are not defined` | contraseña de SYSDBA incorrecta | corrige `FIREBIRD_PASSWORD` |
| `No se pudo conectar a PostgreSQL en localhost:5434` | Docker no está corriendo | abre Docker Desktop y `docker compose up -d` |
| `port is already allocated` al levantar PostgreSQL | otro programa usa el 5434 | cambia `"5434:5432"` en `docker-compose.yml` y `POSTGRES_PORT` en `.env` |
| `Operation not permitted` al leer la base (macOS) | la copia está en Escritorio/Documentos/Descargas | muévela a otra carpeta, p. ej. `~/dev/bases` |
| `scripts/ci_local.sh: $'\r': command not found` (Windows) | Git convirtió el archivo a CRLF | `git config core.autocrlf input` y vuelve a clonar (`.gitattributes` ya fuerza LF en clones nuevos) |
