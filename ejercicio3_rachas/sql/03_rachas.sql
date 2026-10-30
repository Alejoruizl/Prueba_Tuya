-- =============================================================================
-- Ejercicio 3 - Rachas
-- 03_rachas.sql: racha más larga (>= n meses) por cliente en un nivel de deuda,
--                calculada "parado" en :fecha_base.
--
-- Parámetros:
--   :fecha_base  Fecha de referencia 'YYYY-MM-DD'. Solo se conoce información con
--                corte_mes <= fecha_base y retiros con fecha_retiro <= fecha_base.
--   :n           Longitud mínima (en meses) de la racha.
--
-- Uso desde la CLI de sqlite3, sobre la base ya construida (sqlite3 rachas.db).
-- La fecha va con comillas simples dentro de comillas dobles; sin ellas la CLI
-- la evalúa como una resta (2024 - 12 - 31):
--   .parameter set :fecha_base "'2024-12-31'"
--   .parameter set :n 3
--   .read sql/03_rachas.sql
-- =============================================================================

WITH RECURSIVE
parametros AS (
    -- Solo se acepta texto: SQLite interpreta un número como día juliano.
    SELECT CASE WHEN typeof(:fecha_base) = 'text' THEN date(:fecha_base) END AS fecha_base,
           CAST(:n AS INTEGER) AS n
),

-- 1. Foto de la información disponible a la fecha_base. Los retiros no necesitan
--    este filtro: un retiro posterior a la fecha_base nunca excluye un corte
--    menor o igual a ella.
historia_vigente AS (
    SELECT h.identificacion, h.corte_mes, h.saldo
    FROM historia AS h
    CROSS JOIN parametros AS p
    WHERE h.corte_mes <= p.fecha_base
),

-- 2. Calendario de cortes (último día de cada mes) entre el primer y el último
--    corte cargado. No se imputan meses que todavía no existen en la fuente.
calendario (corte_mes, ultimo_corte) AS (
    SELECT MIN(corte_mes), MAX(corte_mes)
    FROM historia_vigente
    UNION ALL
    SELECT date(corte_mes, '+1 day', '+1 month', '-1 day'), ultimo_corte
    FROM calendario
    WHERE corte_mes < ultimo_corte
),

primera_aparicion AS (
    SELECT identificacion,
           MIN(corte_mes) AS primer_corte
    FROM historia_vigente
    GROUP BY identificacion
),

-- 3. Serie mensual de cada cliente desde su primera aparición. Un mes sin registro
--    se imputa con saldo 0 (N0), excepto si el corte es posterior a la fecha de
--    retiro: en ese caso el mes no existe para el cliente.
saldos_mensuales AS (
    SELECT pa.identificacion,
           ca.corte_mes,
           COALESCE(hv.saldo, 0) AS saldo
    FROM primera_aparicion AS pa
    INNER JOIN calendario AS ca
        ON ca.corte_mes >= pa.primer_corte
    LEFT JOIN historia_vigente AS hv
        ON  hv.identificacion = pa.identificacion
        AND hv.corte_mes      = ca.corte_mes
    LEFT JOIN retiros AS r
        ON r.identificacion = pa.identificacion
    WHERE hv.saldo IS NOT NULL
       OR r.fecha_retiro IS NULL
       OR ca.corte_mes <= r.fecha_retiro
),

saldos_clasificados AS (
    SELECT sm.identificacion,
           sm.corte_mes,
           dn.nivel,
           -- número absoluto del mes: dos cortes son consecutivos si difieren en 1
           CAST(strftime('%Y', sm.corte_mes) AS INTEGER) * 12
               + CAST(strftime('%m', sm.corte_mes) AS INTEGER) AS numero_mes
    FROM saldos_mensuales AS sm
    INNER JOIN dim_nivel AS dn
        ON  sm.saldo >= dn.saldo_min
        AND (dn.saldo_max IS NULL OR sm.saldo < dn.saldo_max)
),

-- 4. Gaps and islands: dentro de un cliente y nivel, numero_mes menos la posición
--    del mes es constante mientras los meses sean consecutivos. Un cambio de nivel
--    o un mes inexistente (posterior al retiro) inicia una racha nueva.
islas AS (
    SELECT identificacion, nivel, corte_mes,
           numero_mes - ROW_NUMBER() OVER (PARTITION BY identificacion, nivel
                                           ORDER BY corte_mes) AS id_isla
    FROM saldos_clasificados
),

rachas AS (
    SELECT identificacion, nivel,
           COUNT(*)       AS racha,
           MIN(corte_mes) AS fecha_inicio,
           MAX(corte_mes) AS fecha_fin
    FROM islas
    GROUP BY identificacion, nivel, id_isla
),

-- 5. Filtro por n y desempate: la racha más larga y, a igualdad, la más reciente.
rachas_priorizadas AS (
    SELECT r.identificacion, r.racha, r.fecha_fin, r.nivel,
           ROW_NUMBER() OVER (PARTITION BY r.identificacion
                              ORDER BY r.racha DESC, r.fecha_fin DESC) AS prioridad
    FROM rachas AS r
    CROSS JOIN parametros AS p
    WHERE r.racha >= p.n
)

SELECT identificacion,
       racha,
       fecha_fin,
       nivel
FROM rachas_priorizadas
WHERE prioridad = 1
ORDER BY identificacion;
