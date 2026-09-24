"""Manifiesto de extracción: la declaración versionada de una tabla de CONFIG
(columnas en alcance, regla de normalización de cada una, catálogos contra los
que se valida la integridad referencial, y de dónde sale su snapshot).

Misma idea que en ``migracion-firebird-postgres-clientes``: agregar una tabla
es escribir un YAML, no un módulo de Python. La diferencia es que aquí no hay
PostgreSQL ni DDL de destino — el "candidato" es el conjunto de filas
normalizadas que se escribe como evidencia (CSV/JSON), y la integridad
referencial se verifica contra catálogos extraídos de la misma base CONFIG.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .rutas import raiz_datos, ruta_fuentes

REGLAS_VALIDAS = {
    "texto",
    "bandera_sn",
    "booleano",
    "catalogo_normalizado",
    "decimal",
    "decimal_con_signo",
    "entero",
    "fecha",
    "hora",
    "timestamp",
}


class CampoManifiesto(BaseModel):
    origen: str = Field(..., description="Columna de Firebird (y clave en la fila cruda / fixture)")
    destino: str = Field(..., description="Nombre normalizado en el candidato")
    regla: str = Field(..., description="Regla de normalización (ver reglas/motor.py)")
    nulo_permitido: bool = False
    catalogo_fk: str | None = Field(None, description="Catálogo contra el que se valida la integridad referencial")
    catalogo_dominio: str | None = Field(
        None, description="Para regla=catalogo_normalizado: catálogo derivado con el dominio válido"
    )

    @model_validator(mode="after")
    def _regla_conocida(self) -> CampoManifiesto:
        if self.regla not in REGLAS_VALIDAS:
            raise ValueError(f"campo '{self.destino}': regla desconocida '{self.regla}' (válidas: {sorted(REGLAS_VALIDAS)})")
        return self


class CatalogoManifiesto(BaseModel):
    """``derivado``: valores declarados en el propio manifiesto (dominio de un
    código). ``tabla``: otra tabla de CONFIG, extraída igual que la principal
    (del fixture o de Firebird) — sus ids son el dominio de la FK."""

    nombre: str
    tipo: Literal["derivado", "tabla"]
    columnas: list[str] = Field(..., description="[columna_id, columna_descripcion?] en el candidato")
    valores: list[list[str]] | None = Field(None, description="Solo tipo=derivado")
    tabla_origen: str | None = Field(None, description="Solo tipo=tabla: tabla de CONFIG")
    fixture: str | None = Field(None, description="Solo tipo=tabla: snapshot relativo a la raíz de datos")
    mapeo_columnas: list[list[str]] | None = Field(None, description="Solo tipo=tabla: [[columna_origen, columna_destino], ...]")
    al_borrar: Literal["cascade", "restrict", "set_null", "set_default"] | None = Field(
        None, description="Solo tipo=tabla: regla de borrado de la FK real en origen; se replica en PostgreSQL"
    )

    @model_validator(mode="after")
    def _coherente(self) -> CatalogoManifiesto:
        if self.tipo == "derivado" and not self.valores:
            raise ValueError(f"catálogo '{self.nombre}': tipo derivado requiere 'valores'")
        if self.tipo == "tabla" and not (self.tabla_origen and self.fixture):
            raise ValueError(f"catálogo '{self.nombre}': tipo tabla requiere 'tabla_origen' y 'fixture'")
        return self

    def dominio(self) -> dict[str, str]:
        if self.tipo != "derivado" or not self.valores:
            raise ValueError(f"El catálogo '{self.nombre}' no es de tipo 'derivado'; no tiene dominio inline.")
        return {v[0]: (v[1] if len(v) > 1 else v[0]) for v in self.valores}

    def mapeo(self) -> list[list[str]]:
        return self.mapeo_columnas or [[c.upper(), c] for c in self.columnas]

    @property
    def tabla(self) -> str:
        """``tabla_origen`` de un catálogo tipo 'tabla' (el validador ya exige que exista)."""
        if not self.tabla_origen:
            raise ValueError(f"El catálogo '{self.nombre}' no es de tipo 'tabla'; no tiene tabla de origen.")
        return self.tabla_origen

    def ruta_fixture(self) -> Path:
        if not self.fixture:
            raise ValueError(f"El catálogo '{self.nombre}' no es de tipo 'tabla'; no tiene snapshot.")
        return raiz_datos() / self.fixture


class Manifiesto(BaseModel):
    fuente: str
    tabla_origen: str
    tabla_destino: str
    llave_primaria: str | list[str] = Field(
        ..., description="Nombre(s) `destino` que identifican la fila; lista para llaves compuestas"
    )
    fixture: str = Field(..., description="Snapshot de origen, relativo a la raíz de datos")
    estado: Literal["borrador", "vigente"] = "vigente"
    depende_de: list[str] = Field(default_factory=list)
    campos: list[CampoManifiesto]
    catalogos: list[CatalogoManifiesto] = Field(default_factory=list)
    campo_checksum: str | None = None

    @model_validator(mode="after")
    def _validar_referencias_cruzadas(self) -> Manifiesto:
        nombres_catalogo = {c.nombre for c in self.catalogos}
        destinos = [c.destino for c in self.campos]
        if len(destinos) != len(set(destinos)):
            raise ValueError("hay nombres 'destino' repetidos en campos")
        for campo in self.campos:
            for ref in (campo.catalogo_fk, campo.catalogo_dominio):
                if ref and ref not in nombres_catalogo:
                    raise ValueError(f"campo '{campo.destino}': el catálogo '{ref}' no está declarado en catalogos")
            if campo.regla == "catalogo_normalizado" and not campo.catalogo_dominio:
                raise ValueError(f"campo '{campo.destino}': regla catalogo_normalizado requiere catalogo_dominio")
        for dep in self.depende_de:
            if dep not in nombres_catalogo:
                raise ValueError(f"depende_de='{dep}' no está declarado en catalogos")
        for llave in self.llaves:
            if llave not in destinos:
                raise ValueError(f"llave_primaria: '{llave}' no aparece como destino de ningún campo")
        if self.campo_checksum and self.campo_checksum not in destinos:
            raise ValueError(f"campo_checksum='{self.campo_checksum}' no aparece como destino de ningún campo")
        return self

    def catalogo(self, nombre: str | None) -> CatalogoManifiesto:
        for c in self.catalogos:
            if c.nombre == nombre:
                return c
        raise KeyError(f"Catálogo '{nombre}' no declarado en el manifiesto de {self.tabla_destino}")

    @property
    def llaves(self) -> list[str]:
        return [self.llave_primaria] if isinstance(self.llave_primaria, str) else list(self.llave_primaria)

    @property
    def nombre_llave(self) -> str:
        """Etiqueta de la llave para mensajes: ``usuario_id+derecho_id``."""
        return "+".join(self.llaves)

    def campos_llave(self) -> list[CampoManifiesto]:
        por_destino = {c.destino: c for c in self.campos}
        return [por_destino[k] for k in self.llaves]

    def valor_llave(self, fila_destino: Mapping[str, Any]) -> str:
        """Valor de la llave de una fila normalizada; ``a|b`` si es compuesta."""
        return "|".join(str(fila_destino.get(k)) for k in self.llaves)

    def valor_llave_crudo(self, fila_cruda: Mapping[str, Any]) -> str:
        """Lo mismo para una fila cruda (claves ``origen``). Recorta el relleno
        de CHAR para que coincida con la forma normalizada."""
        return "|".join(
            str(v).strip() if isinstance(v, str) else str(v) for v in (fila_cruda.get(c.origen) for c in self.campos_llave())
        )

    def ruta_fixture(self) -> Path:
        return raiz_datos() / self.fixture


def listar_fuentes() -> list[str]:
    raiz = ruta_fuentes()
    return sorted(p.name for p in raiz.iterdir() if p.is_dir()) if raiz.is_dir() else []


def listar_manifiestos(fuente: str) -> list[str]:
    directorio = ruta_fuentes() / fuente / "manifiestos"
    return sorted(p.stem for p in directorio.glob("*.yaml")) if directorio.is_dir() else []


def ruta_manifiesto(fuente: str, tabla: str) -> Path:
    return ruta_fuentes() / fuente / "manifiestos" / f"{tabla}.yaml"


def cargar_manifiesto(fuente: str, tabla: str) -> Manifiesto:
    ruta = ruta_manifiesto(fuente, tabla)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe manifiesto para fuente='{fuente}' tabla='{tabla}' (esperado en {ruta})")
    return Manifiesto.model_validate(yaml.safe_load(ruta.read_text(encoding="utf-8")))


def ruta_golden(fuente: str, tabla: str) -> Path:
    return ruta_fuentes() / fuente / "golden" / f"{tabla}.json"
