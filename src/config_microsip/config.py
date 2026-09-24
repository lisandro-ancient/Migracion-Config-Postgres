"""Configuración de la conexión a la base CONFIG de Firebird, leída del
entorno (y de ``.env`` en la raíz del repositorio, si existe).

Nunca se hardcodean credenciales. Dos modos de conexión, igual que el MCP de
Firebird de este mismo flujo de trabajo (``~/mcp-firebird``):

- **Embebido** (``FIREBIRD_HOST`` vacío): ``firebird-driver`` abre el archivo
  ``FIREBIRD_DATABASE`` directamente con el motor local de
  ``FIREBIRD_RUNTIME_DIR``, sin ningún Firebird Server escuchando.
- **Remoto** (``FIREBIRD_HOST`` definido): ``host/puerto:ruta`` contra un
  Firebird Server real.

Charset: el runtime embebido de esta máquina no trae el módulo INTL de
ISO8859_1 — conectar con ``charset=ISO8859_1`` falla con "CHARACTER SET
ISO8859_1 is not defined". Por eso el valor por defecto es conectar sin
charset (``NONE``: el servidor entrega los bytes tal cual) y decodificarlos
del lado de Python con ``FIREBIRD_CODIFICACION`` (``iso8859_1`` por defecto,
el charset real de los textos de MicroSIP). Contra un servidor que sí tenga
INTL, se puede fijar ``FIREBIRD_CHARSET=ISO8859_1`` y el servidor decodifica.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .rutas import RUTA_PROYECTO


def cargar_env() -> None:
    """Carga ``.env`` de la raíz del repositorio sin pisar variables ya
    definidas en el entorno (las del proceso siempre ganan)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dependencia de conveniencia, no obligatoria
        return
    load_dotenv(RUTA_PROYECTO / ".env", override=False)


@dataclass(frozen=True)
class ConfigPostgres:
    """PostgreSQL de destino. Los valores por defecto son los del contenedor
    local desechable de docker-compose.yml (puerto 5434)."""

    host: str = "localhost"
    puerto: int = 5434
    base_datos: str = "config_microsip"
    usuario: str = "migracion"
    password: str = "migracion_dev_password"  # noqa: S105 — solo el contenedor local desechable de docker-compose.yml

    @classmethod
    def desde_entorno(cls) -> ConfigPostgres:
        cargar_env()
        return cls(
            host=os.environ.get("POSTGRES_HOST") or "localhost",
            puerto=int(os.environ.get("POSTGRES_PORT") or 5434),
            base_datos=os.environ.get("POSTGRES_DB") or "config_microsip",
            usuario=os.environ.get("POSTGRES_USER") or "migracion",
            password=os.environ.get("POSTGRES_PASSWORD") or "migracion_dev_password",
        )

    def conninfo(self) -> str:
        return (
            f"host={self.host} port={self.puerto} dbname={self.base_datos} "
            f"user={self.usuario} password={self.password} connect_timeout=5"
        )

    def descripcion_segura(self) -> dict:
        return {"host": self.host, "puerto": self.puerto, "base_datos": self.base_datos, "usuario": self.usuario}


class ConfiguracionIncompleta(RuntimeError):
    """Falta una variable obligatoria para conectar a Firebird."""


def _vacio_a_none(valor: str | None) -> str | None:
    return valor.strip() if valor and valor.strip() else None


@dataclass(frozen=True)
class ConfigFirebird:
    base_datos: str
    usuario: str
    password: str
    host: str | None = None
    puerto: int = 3050
    charset: str | None = None  # None = NONE (bytes crudos, decodifica Python)
    codificacion: str = "iso8859_1"
    biblioteca_cliente: str | None = None
    directorio_runtime: str | None = None

    @property
    def embebido(self) -> bool:
        return not self.host

    def dsn(self) -> str:
        if self.embebido:
            return self.base_datos
        return f"{self.host}/{self.puerto}:{self.base_datos}"

    def descripcion_segura(self) -> dict:
        """Lo que se puede mostrar en logs, reportes o herramientas MCP: todo
        menos la contraseña."""
        return {
            "modo": "embebido" if self.embebido else "remoto",
            "dsn": self.dsn(),
            "usuario": self.usuario,
            "charset_conexion": self.charset or "NONE",
            "codificacion_python": self.codificacion if not self.charset else None,
        }

    @classmethod
    def desde_entorno(cls) -> ConfigFirebird:
        cargar_env()
        base_datos = _vacio_a_none(os.environ.get("FIREBIRD_DATABASE"))
        if not base_datos:
            raise ConfiguracionIncompleta(
                "FIREBIRD_DATABASE no está definida. Copia .env.example a .env y apunta "
                "FIREBIRD_DATABASE a tu CONFIG.FDB (ver README, 'Conectar a tu CONFIG.FDB')."
            )
        host = _vacio_a_none(os.environ.get("FIREBIRD_HOST"))
        if not host:
            # En modo embebido la ruta se resuelve a absoluta ahora: la conexión
            # cambia el directorio de trabajo al runtime (ver conexion.py) y una
            # ruta relativa dejaría de apuntar al archivo correcto.
            base_datos = str(Path(base_datos).expanduser().resolve())
        return cls(
            base_datos=base_datos,
            usuario=os.environ.get("FIREBIRD_USER", "SYSDBA"),
            password=os.environ.get("FIREBIRD_PASSWORD", ""),
            host=host,
            puerto=int(os.environ.get("FIREBIRD_PORT") or 3050),
            charset=_vacio_a_none(os.environ.get("FIREBIRD_CHARSET")),
            codificacion=os.environ.get("FIREBIRD_CODIFICACION") or "iso8859_1",
            biblioteca_cliente=_vacio_a_none(os.environ.get("FIREBIRD_CLIENT_LIBRARY")),
            directorio_runtime=_vacio_a_none(os.environ.get("FIREBIRD_RUNTIME_DIR")),
        )
