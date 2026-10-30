-- =============================================================================
-- Ejercicio 3 - Rachas
-- 02_calidad_y_carga.sql: reglas de calidad + paso de staging a capa depurada.
--
-- Prerrequisito: stg_historia y stg_retiros cargadas (ver rachas/cargar_excel.py).
-- El script es idempotente: limpia la capa depurada y la bitácora antes de correr.
-- =============================================================================

DELETE FROM dq_incidencias;
DELETE FROM historia;
DELETE FROM retiros;

-- Registros de historia que superan las reglas de rechazo.
DROP VIEW IF EXISTS temp.v_historia_valida;
CREATE TEMP VIEW v_historia_valida AS
SELECT fila_origen, identificacion, identificacion_original,
       corte_fecha, corte_mes, saldo
FROM v_stg_historia_tipada
WHERE identificacion IS NOT NULL
  AND corte_mes      IS NOT NULL
  AND saldo          IS NOT NULL
  AND saldo >= 0;

DROP VIEW IF EXISTS temp.v_retiros_validos;
CREATE TEMP VIEW v_retiros_validos AS
SELECT fila_origen, identificacion, identificacion_original, fecha_retiro
FROM v_stg_retiros_tipada
WHERE identificacion IS NOT NULL
  AND fecha_retiro   IS NOT NULL;

-- =============================================================================
-- HISTORIA
-- =============================================================================

-- R01: identificación vacía o nula
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R01_IDENTIFICACION_NULA', 'RECHAZO', fila_origen, NULL, corte_mes_original,
       'Registro sin identificación'
FROM v_stg_historia_tipada
WHERE identificacion IS NULL;

-- R02: fecha de corte no interpretable
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R02_CORTE_MES_INVALIDO', 'RECHAZO', fila_origen, identificacion, corte_mes_original,
       'corte_mes no es una fecha válida en formato YYYY-MM-DD'
FROM v_stg_historia_tipada
WHERE identificacion IS NOT NULL
  AND corte_mes IS NULL;

-- R03: saldo nulo o no numérico
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R03_SALDO_NO_NUMERICO', 'RECHAZO', fila_origen, identificacion, corte_mes,
       'saldo = ' || quote(saldo_original)
FROM v_stg_historia_tipada
WHERE identificacion IS NOT NULL
  AND corte_mes IS NOT NULL
  AND saldo IS NULL;

-- R04: saldo negativo (los niveles solo están definidos para saldo >= 0)
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R04_SALDO_NEGATIVO', 'RECHAZO', fila_origen, identificacion, corte_mes,
       'saldo = ' || saldo
FROM v_stg_historia_tipada
WHERE identificacion IS NOT NULL
  AND corte_mes IS NOT NULL
  AND saldo < 0;

-- R05: la fecha de corte no corresponde al último día del mes -> se normaliza
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R05_CORTE_NO_FIN_DE_MES', 'CORRECCION', fila_origen, identificacion, corte_mes,
       'corte original ' || corte_fecha || ' normalizado a ' || corte_mes
FROM v_historia_valida
WHERE corte_fecha <> corte_mes;

-- R06: identificación con espacios o minúsculas -> se normaliza
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R06_IDENTIFICACION_NORMALIZADA', 'CORRECCION', fila_origen, identificacion, corte_mes,
       'identificación original ' || quote(identificacion_original)
FROM v_historia_valida
WHERE CAST(identificacion_original AS TEXT) <> identificacion;

-- R07: duplicado exacto (misma identificación, corte y saldo) -> se colapsa
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R07_DUPLICADO_EXACTO', 'CORRECCION', fila_origen, identificacion, corte_mes,
       'Registro repetido descartado (saldo ' || saldo || ')'
FROM (
    SELECT v.*,
           ROW_NUMBER() OVER (PARTITION BY identificacion, corte_mes, saldo
                              ORDER BY fila_origen) AS nro
    FROM v_historia_valida AS v
)
WHERE nro > 1;

-- R08: mismo cliente y corte con saldos distintos -> se conserva el mayor
--      (criterio conservador de riesgo: no subestimar la deuda).
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R08_DUPLICADO_CONFLICTIVO', 'CORRECCION', v.fila_origen, v.identificacion, v.corte_mes,
       'saldo ' || v.saldo || CASE WHEN v.saldo = c.saldo_max THEN ' (conservado)' ELSE ' (descartado)' END
       || '; saldos en conflicto: ' || c.saldos
FROM v_historia_valida AS v
INNER JOIN (
    SELECT identificacion, corte_mes,
           MAX(saldo)                    AS saldo_max,
           group_concat(DISTINCT saldo)  AS saldos
    FROM v_historia_valida
    GROUP BY identificacion, corte_mes
    HAVING COUNT(DISTINCT saldo) > 1
) AS c
    ON  c.identificacion = v.identificacion
    AND c.corte_mes      = v.corte_mes;

-- Carga de la capa depurada
INSERT INTO historia (identificacion, corte_mes, saldo)
SELECT identificacion, corte_mes, MAX(saldo)
FROM v_historia_valida
GROUP BY identificacion, corte_mes;

-- R09: longitud de identificación distinta a la predominante (posible error de digitación)
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R09_LONGITUD_IDENTIFICACION_ATIPICA', 'ADVERTENCIA', NULL, h.identificacion, NULL,
       'Longitud ' || length(h.identificacion) || ', predominante ' || m.longitud
FROM (SELECT DISTINCT identificacion FROM historia) AS h
CROSS JOIN (
    SELECT length(identificacion) AS longitud
    FROM historia
    GROUP BY length(identificacion)
    ORDER BY COUNT(*) DESC
    LIMIT 1
) AS m
WHERE length(h.identificacion) <> m.longitud;

-- =============================================================================
-- RETIROS
-- =============================================================================

-- R10: identificación o fecha de retiro inválidas
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'retiros',
       CASE WHEN identificacion IS NULL THEN 'R10_IDENTIFICACION_NULA' ELSE 'R10_FECHA_RETIRO_INVALIDA' END,
       'RECHAZO', fila_origen, identificacion, fecha_retiro_original,
       'Registro de retiro no utilizable'
FROM v_stg_retiros_tipada
WHERE identificacion IS NULL
   OR fecha_retiro IS NULL;

-- R11: cliente con más de un retiro -> se conserva el primero
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'retiros', 'R11_RETIRO_DUPLICADO', 'CORRECCION', fila_origen, identificacion, fecha_retiro,
       'Se conserva la fecha de retiro más antigua'
FROM (
    SELECT v.*,
           ROW_NUMBER() OVER (PARTITION BY identificacion ORDER BY fecha_retiro, fila_origen) AS nro
    FROM v_retiros_validos AS v
)
WHERE nro > 1;

INSERT INTO retiros (identificacion, fecha_retiro)
SELECT identificacion, MIN(fecha_retiro)
FROM v_retiros_validos
GROUP BY identificacion;

-- R12: retiro de un cliente que no existe en historia. Se sugieren posibles
--      coincidencias (mismo prefijo y sufijo) pero NO se corrigen automáticamente:
--      reasignar una identificación requiere confirmación de la fuente.
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'retiros', 'R12_RETIRO_SIN_HISTORIA', 'ADVERTENCIA', NULL, r.identificacion, r.fecha_retiro,
       'El cliente no tiene saldos en historia; no se aplica el retiro'
       || COALESCE('. Posible coincidencia: ' || (
              SELECT group_concat(DISTINCT h.identificacion)
              FROM historia AS h
              WHERE substr(h.identificacion, 1, 8) = substr(r.identificacion, 1, 8)
                AND substr(h.identificacion, -3)   = substr(r.identificacion, -3)
          ), '')
FROM retiros AS r
WHERE NOT EXISTS (SELECT 1 FROM historia AS h WHERE h.identificacion = r.identificacion);

-- R09 (retiros): longitud de identificación distinta a la predominante en historia
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'retiros', 'R09_LONGITUD_IDENTIFICACION_ATIPICA', 'ADVERTENCIA', NULL, r.identificacion, r.fecha_retiro,
       'Longitud ' || length(r.identificacion) || ', predominante ' || m.longitud
FROM retiros AS r
CROSS JOIN (
    SELECT length(identificacion) AS longitud
    FROM historia
    GROUP BY length(identificacion)
    ORDER BY COUNT(*) DESC
    LIMIT 1
) AS m
WHERE length(r.identificacion) <> m.longitud;

-- R13: saldos reportados en cortes posteriores a la fecha de retiro. Se conservan:
--      el enunciado solo impide imputar N0 después del retiro, y un cliente que
--      se retira puede seguir teniendo saldo pendiente. Se reportan para seguimiento.
INSERT INTO dq_incidencias (tabla, regla, severidad, fila_origen, identificacion, fecha, detalle)
SELECT 'historia', 'R13_SALDO_POSTERIOR_A_RETIRO', 'ADVERTENCIA', NULL, h.identificacion, h.corte_mes,
       'Retiro el ' || r.fecha_retiro || '; el saldo reportado (' || h.saldo || ') se conserva'
FROM historia AS h
INNER JOIN retiros AS r
    ON r.identificacion = h.identificacion
WHERE h.corte_mes > r.fecha_retiro;

DROP VIEW temp.v_historia_valida;
DROP VIEW temp.v_retiros_validos;
