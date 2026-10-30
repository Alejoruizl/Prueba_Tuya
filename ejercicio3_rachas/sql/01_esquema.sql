-- =============================================================================
-- Ejercicio 3 - Rachas
-- 01_esquema.sql: creación del modelo de datos (SQLite >= 3.25)
--
-- Capas:
--   stg_*          Datos crudos tal como vienen del Excel (sin tipos forzados).
--   dim_nivel      Parametrización de los niveles de deuda.
--   historia,
--   retiros        Datos depurados, tipados y con restricciones de integridad.
--   dq_incidencias Bitácora de reglas de calidad de datos que se dispararon.
-- =============================================================================

DROP VIEW  IF EXISTS v_stg_historia_tipada;
DROP VIEW  IF EXISTS v_stg_retiros_tipada;
DROP TABLE IF EXISTS dq_incidencias;
DROP TABLE IF EXISTS historia;
DROP TABLE IF EXISTS retiros;
DROP TABLE IF EXISTS dim_nivel;
DROP TABLE IF EXISTS stg_historia;
DROP TABLE IF EXISTS stg_retiros;

-- -----------------------------------------------------------------------------
-- Staging: columnas sin afinidad de tipo para conservar el valor original.
-- -----------------------------------------------------------------------------
CREATE TABLE stg_historia (
    fila_origen     INTEGER NOT NULL PRIMARY KEY,  -- fila en la hoja de Excel
    identificacion,
    corte_mes,
    saldo
);

CREATE TABLE stg_retiros (
    fila_origen     INTEGER NOT NULL PRIMARY KEY,
    identificacion,
    fecha_retiro
);

-- -----------------------------------------------------------------------------
-- Niveles de deuda: intervalo [saldo_min, saldo_max). saldo_max NULL = sin tope.
-- Mantenerlos en tabla evita "números mágicos" en la consulta de rachas.
-- -----------------------------------------------------------------------------
CREATE TABLE dim_nivel (
    nivel       TEXT    NOT NULL PRIMARY KEY,
    saldo_min   NUMERIC NOT NULL,
    saldo_max   NUMERIC,
    CHECK (saldo_max IS NULL OR saldo_max > saldo_min)
);

INSERT INTO dim_nivel (nivel, saldo_min, saldo_max) VALUES
    ('N0',       0,   300000),
    ('N1',  300000,  1000000),
    ('N2', 1000000,  3000000),
    ('N3', 3000000,  5000000),
    ('N4', 5000000,     NULL);

-- -----------------------------------------------------------------------------
-- Datos depurados
-- -----------------------------------------------------------------------------
CREATE TABLE historia (
    identificacion  TEXT    NOT NULL,
    corte_mes       TEXT    NOT NULL,   -- ISO-8601, siempre último día del mes
    saldo           NUMERIC NOT NULL,
    PRIMARY KEY (identificacion, corte_mes),
    CHECK (corte_mes = date(corte_mes, 'start of month', '+1 month', '-1 day')),
    CHECK (saldo >= 0)
);

CREATE TABLE retiros (
    identificacion  TEXT NOT NULL PRIMARY KEY,
    fecha_retiro    TEXT NOT NULL,
    CHECK (fecha_retiro = date(fecha_retiro))
);

CREATE INDEX ix_historia_corte_mes ON historia (corte_mes);

-- -----------------------------------------------------------------------------
-- Bitácora de calidad de datos
--   severidad: RECHAZO     -> el registro no pasa a la capa depurada
--              CORRECCION  -> el registro pasa con un ajuste documentado
--              ADVERTENCIA -> el registro pasa; se reporta para seguimiento
-- -----------------------------------------------------------------------------
CREATE TABLE dq_incidencias (
    id_incidencia   INTEGER PRIMARY KEY,
    tabla           TEXT NOT NULL,
    regla           TEXT NOT NULL,
    severidad       TEXT NOT NULL CHECK (severidad IN ('RECHAZO', 'CORRECCION', 'ADVERTENCIA')),
    fila_origen     INTEGER,
    identificacion  TEXT,
    fecha           TEXT,
    detalle         TEXT,
    registrado_en   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- Vistas de tipado: interpretan el dato crudo sin descartar nada, para que las
-- reglas de calidad se escriban una sola vez sobre columnas ya interpretadas.
--
-- Fechas: solo se aceptan textos ISO que date() devuelve sin cambios, porque
-- SQLite convierte '2024-02-30' en '2024-03-01' y un número en un día juliano.
-- Saldos en texto: dígitos, a lo sumo un punto decimal y el signo solo al inicio.
-- -----------------------------------------------------------------------------
CREATE VIEW v_stg_historia_tipada AS
SELECT
    fila_origen,
    identificacion_original,
    identificacion,
    corte_mes_original,
    corte_fecha,
    date(corte_fecha, 'start of month', '+1 month', '-1 day') AS corte_mes,
    saldo_original,
    saldo
FROM (
    SELECT
        fila_origen,
        identificacion                              AS identificacion_original,
        NULLIF(upper(trim(identificacion)), '')     AS identificacion,
        corte_mes                                   AS corte_mes_original,
        CASE
            WHEN typeof(corte_mes) = 'text'
                 AND date(trim(corte_mes)) = substr(trim(corte_mes), 1, 10)
                THEN date(trim(corte_mes))
        END                                         AS corte_fecha,
        saldo                                       AS saldo_original,
        CASE
            WHEN typeof(saldo) IN ('integer', 'real') THEN saldo
            WHEN typeof(saldo) = 'text'
                 AND trim(saldo) GLOB '*[0-9]*'
                 AND trim(saldo) NOT GLOB '*[^0-9.-]*'
                 AND trim(saldo) NOT GLOB '?*-*'
                 AND trim(saldo) NOT GLOB '*.*.*'
                THEN CAST(trim(saldo) AS NUMERIC)
        END                                         AS saldo
    FROM stg_historia
);

CREATE VIEW v_stg_retiros_tipada AS
SELECT
    fila_origen,
    identificacion                                  AS identificacion_original,
    NULLIF(upper(trim(identificacion)), '')         AS identificacion,
    fecha_retiro                                    AS fecha_retiro_original,
    CASE
        WHEN typeof(fecha_retiro) = 'text'
             AND date(trim(fecha_retiro)) = substr(trim(fecha_retiro), 1, 10)
            THEN date(trim(fecha_retiro))
    END                                             AS fecha_retiro
FROM stg_retiros;
