"""Pruebas del prototipo del dataset de teléfonos.  Ejecutar desde ejercicio1_telefonos/:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from telefonos.normalizacion import ErrorNormalizacion, TipoTelefono, normalizar
from telefonos.pipeline import ejecutar, publicar
from telefonos.reglas import Cliente, RegistroCrudo, ValidadorTelefonos, es_numero_basura
from telefonos.supervivencia import ResultadoContacto, Supervivencia

DATOS = Path(__file__).resolve().parent.parent / "data"
HOY = dt.date(2026, 10, 30)


class TestNormalizacion(unittest.TestCase):

    def test_formatos_de_movil(self):
        for valor in ("3001234567", "+57 300 123 4567", "+57 (300) 123-4567", "0057 3001234567",
                      "573001234567", "03001234567", " 300-123-4567 "):
            with self.subTest(valor=valor):
                t = normalizar(valor)
                self.assertEqual((t.e164, t.tipo), ("+573001234567", TipoTelefono.MOVIL))

    def test_fijos(self):
        self.assertEqual(normalizar("6041234567").tipo, TipoTelefono.FIJO)
        self.assertEqual(normalizar("+57 604 123 4567").e164, "+576041234567")
        # Fijo antiguo de 7 dígitos: se completa con el indicativo de la ciudad del cliente
        self.assertEqual(normalizar("2345678", ciudad="Medellín").e164, "+576042345678")
        self.assertEqual(normalizar("2345678", ciudad="BOGOTA").e164, "+576012345678")

    def test_rechazos(self):
        casos = {"": "vacío", None: "vacío", "abc": "Sin dígitos", "30012345": "Longitud",
                 "2345678": "sin ciudad", "4001234567": "Prefijo", "6091234567": "Prefijo",
                 "+1 555 123 4567": "Longitud"}
        for valor, fragmento in casos.items():
            with self.subTest(valor=valor), self.assertRaisesRegex(ErrorNormalizacion, fragmento):
                normalizar(valor)

    def test_numeros_basura(self):
        self.assertTrue(es_numero_basura("3000000000"))
        self.assertTrue(es_numero_basura("3111111111"))
        self.assertTrue(es_numero_basura("3123456789"))
        self.assertFalse(es_numero_basura("3001234567"))
        self.assertFalse(es_numero_basura("6044445566"))


class TestReglas(unittest.TestCase):

    def setUp(self):
        self.clientes = {"A": Cliente("A", "Medellín", True), "B": Cliente("B", "Bogotá", False),
                         "C": Cliente("C", "Cali", True), "D": Cliente("D", "Cali", True)}
        self.validador = ValidadorTelefonos(self.clientes, {"+573009999999": "pruebas"})

    def _crudo(self, cliente, telefono, fuente="core", fila=2):
        return RegistroCrudo(cliente, telefono, fuente, HOY, fila)

    def test_cada_regla(self):
        validos, rechazos = self.validador.validar([
            self._crudo("A", "3001234567"),           # válido
            self._crudo("A", "30012"),                # T01
            self._crudo("A", "3111111111"),           # T02
            self._crudo("A", "3009999999"),           # T03
            self._crudo("Z", "3001234567"),           # T05
            self._crudo("B", "3151234567"),           # válido, pero sin autorización (T06)
        ])
        self.assertEqual([r.regla for r in rechazos],
                         ["T01_FORMATO_INVALIDO", "T02_NUMERO_BASURA", "T03_LISTA_NEGRA", "T05_CLIENTE_INEXISTENTE"])
        self.assertEqual([(v.cliente_id, v.marcas) for v in validos],
                         [("A", []), ("B", ["T06_SIN_AUTORIZACION"])])

    def test_telefono_compartido(self):
        validos, _ = self.validador.validar([self._crudo(c, "3001234567") for c in "ACD"]
                                            + [self._crudo("A", "3159876543")])
        marcas = {(v.cliente_id, v.e164): v.marcas for v in validos}
        self.assertEqual(marcas[("A", "+573001234567")], ["T04_TELEFONO_COMPARTIDO"])
        self.assertEqual(marcas[("A", "+573159876543")], [])


class TestSupervivencia(unittest.TestCase):

    CONFIG = {"peso_fuente": {"core": 0.4, "app": 0.3}, "bono_verificado": 0.3,
              "dias_recencia": 365, "penalizacion_rebote": 0.15}

    def _validar(self, crudos):
        clientes = {"A": Cliente("A", "Medellín", True)}
        return ValidadorTelefonos(clientes, {}).validar(crudos)[0]

    def test_verificacion_y_rebotes_cambian_el_principal(self):
        validos = self._validar([
            RegistroCrudo("A", "3001111111", "core", HOY, 2),                      # fuente fuerte...
            RegistroCrudo("A", "3002222222", "app", HOY - dt.timedelta(days=30), 3),
        ])
        contactos = [ResultadoContacto("+573001111111", HOY, "NUMERO_ERRADO"),    # ...pero rebota
                     ResultadoContacto("+573002222222", HOY, "EFECTIVO")]          # y este se verificó
        gold = Supervivencia(self.CONFIG, contactos, HOY).elegir(validos)
        principal = next(g for g in gold if g.es_principal)
        self.assertEqual(principal.telefono_e164, "+573002222222")
        self.assertEqual(principal.fecha_ultima_verificacion, HOY)
        self.assertEqual(sum(g.es_principal for g in gold), 1)

    def test_mismo_numero_en_varias_fuentes_queda_una_vez(self):
        validos = self._validar([RegistroCrudo("A", "3001111111", "core", HOY, 2),
                                 RegistroCrudo("A", "+57 300 111 1111", "app", HOY, 2)])
        gold = Supervivencia(self.CONFIG, [], HOY).elegir(validos)
        self.assertEqual(len(gold), 1)
        self.assertEqual(gold[0].fuente_origen, "core")   # la de mayor peso


class TestPipeline(unittest.TestCase):

    def test_corrida_de_ejemplo_publica(self):
        resultado = ejecutar(DATOS, HOY)
        self.assertTrue(resultado.publicable)
        principales = [g for g in resultado.gold if g.es_principal]
        self.assertEqual(len(principales), len({(g.cliente_id, g.tipo) for g in principales}))
        self.assertEqual(sorted({r.regla for r in resultado.cuarentena}),
                         ["T01_FORMATO_INVALIDO", "T02_NUMERO_BASURA", "T03_LISTA_NEGRA", "T05_CLIENTE_INEXISTENTE"])
        sin_autorizacion = [g for g in resultado.gold if g.cliente_id == "C003"]
        self.assertTrue(sin_autorizacion and not any(g.apto_contacto for g in sin_autorizacion))

    def test_gate_fallido_no_publica_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = Path(tmp) / "data"
            shutil.copytree(DATOS, datos)
            config = json.loads((datos / "config.json").read_text(encoding="utf-8"))
            config["quality_gates"]["tasa_cuarentena_maxima"] = 0.01      # umbral imposible
            (datos / "config.json").write_text(json.dumps(config), encoding="utf-8")

            resultado = ejecutar(datos, HOY)
            salida = Path(tmp) / "salida"
            publicar(resultado, salida, HOY)

            self.assertFalse(resultado.publicable)
            self.assertFalse((salida / "dim_cliente_telefono.csv").exists())
            self.assertTrue((salida / "cuarentena.csv").exists())
            reporte = json.loads((salida / "reporte_gates.json").read_text(encoding="utf-8"))
            self.assertFalse(reporte["publicado"])
            self.assertIn("tasa_cuarentena_maxima", [g["gate"] for g in reporte["gates"] if not g["pasa"]])


if __name__ == "__main__":
    unittest.main()
