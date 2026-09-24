-- config.BOOKMARKS_REPORTES (Firebird) -> config.bookmarks_reportes (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."bookmarks_reportes" (
    "reporte_id" BIGINT NOT NULL,
    "objeto_id" BIGINT NOT NULL,
    "fecha" DATE,
    "orden_seleccion" BIGINT,
    CONSTRAINT "pk_bookmarks_reportes" PRIMARY KEY ("reporte_id", "objeto_id")
);

-- config.EMPRESAS (Firebird) -> config.empresas (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."empresas" (
    "empresa_id" BIGINT NOT NULL,
    "nombre_corto" TEXT NOT NULL,
    "usuario_creador" TEXT,
    "fecha_hora_creacion" TIMESTAMP,
    "usuario_ult_modif" TEXT,
    "fecha_hora_ult_modif" TIMESTAMP,
    CONSTRAINT "pk_empresas" PRIMARY KEY ("empresa_id")
);

-- config.SERVIDORES_CORREO (Firebird) -> config.servidores_correo (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."servidores_correo" (
    "servidor_correo_id" BIGINT NOT NULL,
    "nombre" TEXT NOT NULL,
    "proveedor_autenticacion" TEXT NOT NULL,
    "servidor" TEXT NOT NULL,
    "puerto" BIGINT NOT NULL,
    "usuario_creador" TEXT,
    "fecha_hora_creacion" TIMESTAMP,
    "usuario_ult_modif" TEXT,
    "fecha_hora_ult_modif" TIMESTAMP,
    CONSTRAINT "pk_servidores_correo" PRIMARY KEY ("servidor_correo_id")
);

-- config.USUARIOS (Firebird) -> config.usuarios (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."usuarios" (
    "usuario_id" BIGINT NOT NULL,
    "nombre" TEXT NOT NULL,
    "tipo" TEXT,
    "acceso_empresas" TEXT,
    "usar_rol" TEXT,
    "rol_id" BIGINT,
    "estatus" TEXT NOT NULL,
    "autorizador" TEXT NOT NULL,
    "usuario_creador" TEXT,
    "fecha_hora_creacion" TIMESTAMP,
    "usuario_ult_modif" TEXT,
    "fecha_hora_ult_modif" TIMESTAMP,
    CONSTRAINT "pk_usuarios" PRIMARY KEY ("usuario_id"),
    CONSTRAINT "fk_usuarios_rol_id" FOREIGN KEY ("rol_id") REFERENCES "config"."usuarios" ("usuario_id") ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

-- config.CUENTAS_WHATSAPP (Firebird) -> config.cuentas_whatsapp (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."cuentas_whatsapp" (
    "cuenta_whatsapp_id" BIGINT NOT NULL,
    "nombre" TEXT NOT NULL,
    "nombre_usuario" TEXT NOT NULL,
    "num_telefono" TEXT NOT NULL,
    "id_num_telefono" TEXT NOT NULL,
    "id_business" TEXT NOT NULL,
    "id_business_account" TEXT NOT NULL,
    "usuario_creador" TEXT,
    "fecha_hora_creacion" TIMESTAMP,
    "usuario_ult_modif" TEXT,
    "fecha_hora_ult_modif" TIMESTAMP,
    CONSTRAINT "pk_cuentas_whatsapp" PRIMARY KEY ("cuenta_whatsapp_id")
);

-- config.EVENTOS (Firebird) -> config.eventos (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."eventos" (
    "evento_id" BIGINT NOT NULL,
    "candado_id" TEXT,
    "clave_evento" TEXT NOT NULL,
    "fecha" DATE NOT NULL,
    "hora" TIME NOT NULL,
    "uuid" TEXT NOT NULL,
    "llave_primaria" TEXT NOT NULL,
    "atributos_adicionales" TEXT,
    "sincronizado" BOOLEAN,
    "depurar" BOOLEAN,
    "duracion_minutos" NUMERIC NOT NULL,
    "num_instancias" BIGINT,
    "periodicidad" TEXT NOT NULL,
    "fin_periodo" DATE,
    "sincronizar_diario" BOOLEAN,
    CONSTRAINT "pk_eventos" PRIMARY KEY ("evento_id")
);

-- config.RB_FOLDER (Firebird) -> config.rb_folder (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."rb_folder" (
    "folder_id" BIGINT,
    "name" TEXT NOT NULL,
    "parent_id" BIGINT NOT NULL,
    CONSTRAINT "pk_rb_folder" PRIMARY KEY ("name", "parent_id")
);

-- config.RB_ITEM (Firebird) -> config.rb_item (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."rb_item" (
    "item_id" BIGINT,
    "folder_id" BIGINT NOT NULL,
    "name" TEXT NOT NULL,
    "item_size" BIGINT,
    "item_type" BIGINT NOT NULL,
    "modified" NUMERIC NOT NULL,
    "deleted" NUMERIC,
    CONSTRAINT "pk_rb_item" PRIMARY KEY ("folder_id", "item_type", "name", "modified")
);

-- config.REGISTRY (Firebird) -> config.registry (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."registry" (
    "elemento_id" BIGINT NOT NULL,
    "nombre" TEXT NOT NULL,
    "tipo" TEXT NOT NULL,
    "padre_id" BIGINT NOT NULL,
    "valor" TEXT,
    "valor_memo" TEXT,
    CONSTRAINT "pk_registry" PRIMARY KEY ("elemento_id")
);

-- config.VERSIONES_DB (Firebird) -> config.versiones_db (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."versiones_db" (
    "version_db" BIGINT NOT NULL,
    "fecha_hora_creacion" TIMESTAMP,
    "paso_actual" BIGINT NOT NULL,
    CONSTRAINT "pk_versiones_db" PRIMARY KEY ("version_db")
);

-- config.CUENTAS_CORREO (Firebird) -> config.cuentas_correo (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."cuentas_correo" (
    "cuenta_correo_id" BIGINT NOT NULL,
    "tipo" TEXT NOT NULL,
    "empresa_id" BIGINT,
    "usuario_id" BIGINT,
    "descripcion" TEXT NOT NULL,
    "servidor_correo_id" BIGINT NOT NULL,
    "dir_correo" TEXT NOT NULL,
    "nombre_remitente" TEXT NOT NULL,
    "usuario_creador" TEXT,
    "fecha_hora_creacion" TIMESTAMP,
    "usuario_ult_modif" TEXT,
    "fecha_hora_ult_modif" TIMESTAMP,
    CONSTRAINT "pk_cuentas_correo" PRIMARY KEY ("cuenta_correo_id"),
    CONSTRAINT "fk_cuentas_correo_empresa_id" FOREIGN KEY ("empresa_id") REFERENCES "config"."empresas" ("empresa_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_cuentas_correo_usuario_id" FOREIGN KEY ("usuario_id") REFERENCES "config"."usuarios" ("usuario_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_cuentas_correo_servidor_correo_id" FOREIGN KEY ("servidor_correo_id") REFERENCES "config"."servidores_correo" ("servidor_correo_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- config.DERECHOS_USUARIOS (Firebird) -> config.derechos_usuarios (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."derechos_usuarios" (
    "usuario_id" BIGINT NOT NULL,
    "clave_objeto" TEXT NOT NULL,
    CONSTRAINT "pk_derechos_usuarios" PRIMARY KEY ("usuario_id", "clave_objeto"),
    CONSTRAINT "fk_derechos_usuarios_usuario_id" FOREIGN KEY ("usuario_id") REFERENCES "config"."usuarios" ("usuario_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- config.EMPRESAS_USUARIOS (Firebird) -> config.empresas_usuarios (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."empresas_usuarios" (
    "usuario_id" BIGINT NOT NULL,
    "empresa_id" BIGINT NOT NULL,
    CONSTRAINT "pk_empresas_usuarios" PRIMARY KEY ("usuario_id", "empresa_id"),
    CONSTRAINT "fk_empresas_usuarios_usuario_id" FOREIGN KEY ("usuario_id") REFERENCES "config"."usuarios" ("usuario_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_empresas_usuarios_empresa_id" FOREIGN KEY ("empresa_id") REFERENCES "config"."empresas" ("empresa_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- config.EMPRESAS_CUENTAS_WHATSAPP (Firebird) -> config.empresas_cuentas_whatsapp (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."empresas_cuentas_whatsapp" (
    "empresa_id" BIGINT NOT NULL,
    "cuenta_whatsapp_id" BIGINT NOT NULL,
    "activo" BOOLEAN NOT NULL,
    CONSTRAINT "pk_empresas_cuentas_whatsapp" PRIMARY KEY ("empresa_id"),
    CONSTRAINT "fk_empresas_cuentas_whatsapp_empresa_id" FOREIGN KEY ("empresa_id") REFERENCES "config"."empresas" ("empresa_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT "fk_empresas_cuentas_whatsapp_cuenta_whatsapp_id" FOREIGN KEY ("cuenta_whatsapp_id") REFERENCES "config"."cuentas_whatsapp" ("cuenta_whatsapp_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- config.PLANTILLAS_WHATSAPP (Firebird) -> config.plantillas_whatsapp (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."plantillas_whatsapp" (
    "plantilla_whatsapp_id" BIGINT NOT NULL,
    "cuenta_whatsapp_id" BIGINT NOT NULL,
    "nombre" TEXT NOT NULL,
    "tipo" TEXT NOT NULL,
    "contenido" TEXT NOT NULL,
    CONSTRAINT "pk_plantillas_whatsapp" PRIMARY KEY ("plantilla_whatsapp_id"),
    CONSTRAINT "fk_plantillas_whatsapp_cuenta_whatsapp_id" FOREIGN KEY ("cuenta_whatsapp_id") REFERENCES "config"."cuentas_whatsapp" ("cuenta_whatsapp_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- config.PLANTILLAS_WHATSAPP_SIS (Firebird) -> config.plantillas_whatsapp_sis (PostgreSQL)
-- Generado desde el manifiesto por config_microsip.harness_migracion.ddl_tabla.
CREATE SCHEMA IF NOT EXISTS "config";
CREATE TABLE IF NOT EXISTS "config"."plantillas_whatsapp_sis" (
    "plantillas_whatsapp_sis_id" BIGINT NOT NULL,
    "plantilla_whatsapp_id" BIGINT NOT NULL,
    "clave_sistema" TEXT NOT NULL,
    CONSTRAINT "pk_plantillas_whatsapp_sis" PRIMARY KEY ("plantillas_whatsapp_sis_id"),
    CONSTRAINT "fk_plantillas_whatsapp_sis_plantilla_whatsapp_id" FOREIGN KEY ("plantilla_whatsapp_id") REFERENCES "config"."plantillas_whatsapp" ("plantilla_whatsapp_id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);
