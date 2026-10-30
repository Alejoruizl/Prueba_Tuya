"""Pruebas del ejercicio de rachas.

- Casos sintéticos: cada regla del enunciado aislada en un escenario pequeño.
- Validación cruzada: la consulta SQL se compara contra una implementación
  independiente en Python puro sobre los datos reales, para varias fechas base y n.

Ejecutar desde ejercicio3_rachas/:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import calendar
import datetime as dt
import sqlite3
import unittest
from pathlib import Path

from rachas.pipeline import Racha, calcular_rachas, construir_base, crear_esquema, depurar

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "Rachas.xlsx"
D = dt.date.fromisoformat


def _base_vacia() -> sqlite3.Connection:
    conexion = sqlite3.connect(":memory:")
    crear_esquema(conexion)
    return conexion


def _insertar(conexion, historia=(), retiros=()) -> None:
    conexion.executemany("INSERT INTO historia VALUES (?, ?, ?)", historia)
    conexion.executemany("INSERT INTO retiros VALUES (?, ?)", retiros)


def _por_cliente(rachas: list[Racha]) -> dict[str, tuple[int, str, str]]:
    return {r.identificacion: (r.racha, r.fecha_fin, r.nivel) for r in rachas}


class TestReglasDeRachas(unittest.TestCase):

    def setUp(self):
        self.db = _base_vacia()

    def tearDown(self):
        self.db.close()

    def test_limites_de_niveles(self):
        casos = {"A": 299_999, "B": 300_000, "C": 999_999, "D": 1_000_000,
                 "E": 3_000_000, "F": 4_999_999, "G": 5_000_000, "H": 0}
        _insertar(self.db, [(c, "2024-01-31", s) for c, s in casos.items()])
        niveles = {c: nivel for c, (_, _, nivel) in
                   _por_cliente(calcular_rachas(self.db, D("2024-01-31"), 1)).items()}
        self.assertEqual(niveles, {"A": "N0", "B": "N1", "C": "N1", "D": "N2",
                                   "E": "N3", "F": "N3", "G": "N4", "H": "N0"})

    def test_mes_faltante_se_imputa_como_n0(self):
        _insertar(self.db, [("A", "2024-01-31", 100_000), ("A", "2024-03-31", 200_000)])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-03-31"), 3))
        self.assertEqual(resultado, {"A": (3, "2024-03-31", "N0")})

    def test_meses_finales_sin_registro_se_imputan_hasta_el_ultimo_corte(self):
        _insertar(self.db, [
            ("A", "2024-01-31", 4_000_000),
            ("B", "2024-01-31", 4_000_000),
            ("B", "2024-02-29", 4_000_000),
            ("B", "2024-03-31", 4_000_000),
            ("B", "2024-04-30", 4_000_000),
        ])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-12-31"), 2))
        self.assertEqual(resultado["A"], (3, "2024-04-30", "N0"))

    def test_no_se_imputa_antes_de_la_primera_aparicion(self):
        _insertar(self.db, [("A", "2024-01-31", 0), ("B", "2024-03-31", 0)])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-03-31"), 1))
        self.assertEqual(resultado["B"], (1, "2024-03-31", "N0"))

    def test_gana_la_racha_mas_larga_aunque_sea_mas_antigua(self):
        historia = [("A", f"2024-0{m}-{calendar.monthrange(2024, m)[1]}", s) for m, s in
                    [(1, 6e6), (2, 6e6), (3, 6e6), (4, 2e6), (5, 2e6)]]
        _insertar(self.db, historia)
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-05-31"), 2))
        self.assertEqual(resultado["A"], (3, "2024-03-31", "N4"))

    def test_empate_gana_la_racha_mas_reciente(self):
        historia = [("A", f"2024-0{m}-{calendar.monthrange(2024, m)[1]}", s) for m, s in
                    [(1, 6e6), (2, 6e6), (3, 2e6), (4, 2e6)]]
        _insertar(self.db, historia)
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-04-30"), 2))
        self.assertEqual(resultado["A"], (2, "2024-04-30", "N2"))

    def test_clientes_sin_racha_minima_no_aparecen(self):
        _insertar(self.db, [("A", "2024-01-31", 6e6), ("A", "2024-02-29", 0)])
        self.assertEqual(calcular_rachas(self.db, D("2024-02-29"), 2), [])

    def test_no_se_imputa_n0_despues_del_retiro(self):
        historia = [("A", "2024-01-31", 500_000), ("B", "2024-01-31", 0), ("B", "2024-06-30", 0)]
        _insertar(self.db, historia, retiros=[("A", "2024-02-10")])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-06-30"), 1))
        # Sin el retiro, A tendría una racha N0 de febrero a junio.
        self.assertEqual(resultado["A"], (1, "2024-01-31", "N1"))

    def test_saldo_reportado_despues_del_retiro_se_conserva(self):
        historia = [("A", "2024-01-31", 500_000), ("A", "2024-02-29", 500_000),
                    ("A", "2024-03-31", 500_000), ("B", "2024-06-30", 0)]
        _insertar(self.db, historia, retiros=[("A", "2024-02-10")])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-06-30"), 1))
        self.assertEqual(resultado["A"], (3, "2024-03-31", "N1"))

    def test_mes_inexistente_tras_el_retiro_corta_la_racha(self):
        historia = [("A", "2024-01-31", 500_000), ("A", "2024-02-29", 500_000),
                    ("A", "2024-04-30", 500_000), ("B", "2024-04-30", 0)]
        _insertar(self.db, historia, retiros=[("A", "2024-02-10")])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-04-30"), 1))
        # Marzo no existe para A (posterior al retiro y sin reporte): enero-febrero y abril no son consecutivos.
        self.assertEqual(resultado["A"], (2, "2024-02-29", "N1"))

    def test_retiro_en_fin_de_mes_incluye_ese_corte(self):
        historia = [("A", "2024-01-31", 0), ("B", "2024-06-30", 0)]
        _insertar(self.db, historia, retiros=[("A", "2024-02-29")])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-06-30"), 1))
        # Febrero (corte 2024-02-29 <= retiro) se imputa N0; marzo en adelante no.
        self.assertEqual(resultado["A"], (2, "2024-02-29", "N0"))

    def test_retiro_posterior_a_fecha_base_no_afecta(self):
        historia = [("A", "2024-01-31", 0), ("B", "2024-04-30", 0)]
        _insertar(self.db, historia, retiros=[("A", "2024-05-15")])
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-04-30"), 1))
        self.assertEqual(resultado["A"], (4, "2024-04-30", "N0"))

    def test_fecha_base_ignora_cortes_futuros(self):
        historia = [("A", "2024-01-31", 6e6), ("A", "2024-02-29", 6e6), ("A", "2024-03-31", 6e6)]
        _insertar(self.db, historia)
        resultado = _por_cliente(calcular_rachas(self.db, D("2024-03-15"), 1))
        self.assertEqual(resultado["A"], (2, "2024-02-29", "N4"))

    def test_fecha_base_anterior_a_todos_los_datos(self):
        _insertar(self.db, [("A", "2024-01-31", 6e6)])
        self.assertEqual(calcular_rachas(self.db, D("2023-01-01"), 1), [])

    def test_n_invalido(self):
        with self.assertRaises(ValueError):
            calcular_rachas(self.db, D("2024-01-31"), 0)


class TestCalidadDeDatos(unittest.TestCase):

    def setUp(self):
        self.db = _base_vacia()

    def tearDown(self):
        self.db.close()

    def _cargar_staging(self, historia, retiros=()):
        self.db.executemany(
            "INSERT INTO stg_historia (fila_origen, identificacion, corte_mes, saldo) VALUES (?, ?, ?, ?)",
            [(i, *fila) for i, fila in enumerate(historia, start=2)],
        )
        self.db.executemany(
            "INSERT INTO stg_retiros (fila_origen, identificacion, fecha_retiro) VALUES (?, ?, ?)",
            [(i, *fila) for i, fila in enumerate(retiros, start=2)],
        )
        depurar(self.db)

    def _reglas(self) -> dict[str, int]:
        return dict(self.db.execute(
            "SELECT regla, COUNT(*) FROM dq_incidencias GROUP BY regla").fetchall())

    def test_rechazos_y_correcciones(self):
        self._cargar_staging([
            ("AAA", "2024-01-31", 100),          # válido
            ("AAA", "2024-01-31", 100),          # duplicado exacto
            ("BBB", "2024-01-31", 100),          # conflicto: se conserva 900
            ("BBB", "2024-01-31", 900),
            (" ccc ", "2024-01-15", "500"),      # id y corte normalizados, saldo texto
            (None, "2024-01-31", 100),           # sin identificación
            ("DDD", "no-es-fecha", 100),         # fecha inválida
            ("DDD", "2024-02-30", 100),          # fecha inexistente (SQLite la movería a marzo)
            ("DDD", 45322, 100),                 # número de serie de Excel sin convertir
            ("EEE", "2024-01-31", "abc"),        # saldo no numérico
            ("EEE", "2024-02-29", "1.2.3"),      # saldo con formato inválido
            ("FFF", "2024-01-31", -5),           # saldo negativo
            ("FFF", "2024-02-29", " -300 "),     # saldo negativo en texto
        ], retiros=[("AAA", "2024-05-01"), ("AAA", "2024-03-01"), ("ZZZ", "2024-01-01")])

        self.assertEqual(self._reglas(), {
            "R01_IDENTIFICACION_NULA": 1,
            "R02_CORTE_MES_INVALIDO": 3,
            "R03_SALDO_NO_NUMERICO": 2,
            "R04_SALDO_NEGATIVO": 2,
            "R05_CORTE_NO_FIN_DE_MES": 1,
            "R06_IDENTIFICACION_NORMALIZADA": 1,
            "R07_DUPLICADO_EXACTO": 1,
            "R08_DUPLICADO_CONFLICTIVO": 2,
            "R11_RETIRO_DUPLICADO": 1,
            "R12_RETIRO_SIN_HISTORIA": 1,
        })
        historia = self.db.execute("SELECT * FROM historia ORDER BY 1").fetchall()
        self.assertEqual(historia, [("AAA", "2024-01-31", 100), ("BBB", "2024-01-31", 900),
                                    ("CCC", "2024-01-31", 500)])
        retiros = self.db.execute("SELECT * FROM retiros ORDER BY 1").fetchall()
        self.assertEqual(retiros, [("AAA", "2024-03-01"), ("ZZZ", "2024-01-01")])


# -----------------------------------------------------------------------------
# Implementación de referencia (Python puro) para la validación cruzada
# -----------------------------------------------------------------------------
LIMITES = [(0, "N0"), (300_000, "N1"), (1_000_000, "N2"), (3_000_000, "N3"), (5_000_000, "N4")]


def _nivel(saldo: float) -> str:
    return [nombre for minimo, nombre in LIMITES if saldo >= minimo][-1]


def _fin_de_mes(anio: int, mes: int) -> dt.date:
    return dt.date(anio, mes, calendar.monthrange(anio, mes)[1])


def _indice(fecha: dt.date) -> int:
    return fecha.year * 12 + fecha.month - 1


def _corte_de_indice(i: int) -> dt.date:
    return _fin_de_mes(i // 12, i % 12 + 1)


def rachas_referencia(historia, retiros, fecha_base: dt.date, n: int) -> list[Racha]:
    saldos = {(c, D(f)): s for c, f, s in historia if D(f) <= fecha_base}
    if not saldos:
        return []
    ultimo_global = _indice(max(f for _, f in saldos))
    retiro = {c: D(f) for c, f in retiros if D(f) <= fecha_base}

    resultado = []
    for cliente in sorted({c for c, _ in saldos}):
        inicio = _indice(min(f for c, f in saldos if c == cliente))

        tramos = []  # [nivel, longitud, indice_fin]
        for i in range(inicio, ultimo_global + 1):
            corte = _corte_de_indice(i)
            if (cliente, corte) in saldos:
                nivel = _nivel(saldos[(cliente, corte)])
            elif cliente not in retiro or corte <= retiro[cliente]:
                nivel = "N0"
            else:
                continue  # posterior al retiro y sin reporte: el mes no existe

            if tramos and tramos[-1][0] == nivel and tramos[-1][2] == i - 1:
                tramos[-1][1] += 1
                tramos[-1][2] = i
            else:
                tramos.append([nivel, 1, i])

        candidatos = [t for t in tramos if t[1] >= n]
        if candidatos:
            nivel, longitud, i_fin = max(candidatos, key=lambda t: (t[1], t[2]))
            resultado.append(Racha(cliente, longitud, _corte_de_indice(i_fin).isoformat(), nivel))
    return resultado


@unittest.skipUnless(RUTA_EXCEL.exists(), "No se encontró data/Rachas.xlsx")
class TestValidacionCruzadaDatosReales(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(":memory:")
        construir_base(cls.db, RUTA_EXCEL)
        cls.historia = cls.db.execute("SELECT * FROM historia").fetchall()
        cls.retiros = cls.db.execute("SELECT * FROM retiros").fetchall()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_sql_coincide_con_referencia(self):
        fechas = ["2023-01-31", "2023-06-15", "2023-11-30", "2024-01-25",
                  "2024-06-30", "2024-10-31", "2024-12-31", "2025-06-30"]
        for fecha in fechas:
            for n in (1, 2, 3, 4, 6):
                with self.subTest(fecha_base=fecha, n=n):
                    esperado = rachas_referencia(self.historia, self.retiros, D(fecha), n)
                    self.assertEqual(calcular_rachas(self.db, D(fecha), n), esperado)

    def test_incidencias_de_calidad_esperadas(self):
        reglas = dict(self.db.execute(
            "SELECT regla, COUNT(*) FROM dq_incidencias GROUP BY regla").fetchall())
        self.assertEqual(reglas, {
            "R07_DUPLICADO_EXACTO": 1,
            "R08_DUPLICADO_CONFLICTIVO": 2,
            "R09_LONGITUD_IDENTIFICACION_ATIPICA": 1,
            "R12_RETIRO_SIN_HISTORIA": 1,
            "R13_SALDO_POSTERIOR_A_RETIRO": 14,
        })


if __name__ == "__main__":
    unittest.main()
