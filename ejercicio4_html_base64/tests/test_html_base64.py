"""Pruebas del procesador de HTML.  Ejecutar desde ejercicio4_html_base64/:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import base64
import contextlib
import functools
import http.server
import io
import mimetypes
import tempfile
import threading
import unittest
from pathlib import Path

from html_base64 import ejecutar
from html_base64.cli import main
from html_base64.descubrimiento import BuscadorHtml
from html_base64.fuentes import ErrorImagen, detectar_mime
from html_base64.html_img import extraer_imagenes, reemplazar_etiquetas

# PNG válido de 1x1 píxel
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'
DATA_PNG = "data:image/png;base64," + base64.b64encode(PNG).decode()


class TestHtmlImg(unittest.TestCase):

    def test_detecta_variantes_de_sintaxis(self):
        html = ("<p>hola</p>\r\n<IMG SRC='a.png' alt=\"x\">\n"
                "<img data-src=\"no.png\" src=b.png />\n"
                "<!-- <img src=\"comentario.png\"> -->\n"
                "<script>var s = '<img src=\"script.png\">';</script>\n"
                "<img alt=\"src=trampa.png\" src=\"c&amp;d.png\">")
        etiquetas = extraer_imagenes(html)
        self.assertEqual([e.src for e in etiquetas], ["a.png", "b.png", "c&d.png"])
        for etiqueta in etiquetas:
            self.assertEqual(html[etiqueta.inicio:etiqueta.fin], etiqueta.texto)

    def test_reemplazo_conserva_el_resto_del_documento(self):
        html = "<html>\n<img data-src='x' src=\"a.png\" class=c>\n<img alt=\"src=a\" src=b.png></html>"
        etiquetas = extraer_imagenes(html)
        nuevo = reemplazar_etiquetas(html, {etiquetas[0]: etiquetas[0].con_src("NUEVO1"),
                                            etiquetas[1]: etiquetas[1].con_src("NUEVO2")})
        self.assertEqual(
            nuevo,
            "<html>\n<img data-src='x' src=\"NUEVO1\" class=c>\n<img alt=\"src=a\" src=\"NUEVO2\"></html>",
        )

    def test_valor_sin_comillas_con_signo_igual(self):
        # Como en html.parser y en los navegadores, el valor llega hasta el espacio.
        html = "<img src=logo.png?v=2 alt=x>"
        etiqueta = extraer_imagenes(html)[0]
        self.assertEqual(etiqueta.src, "logo.png?v=2")
        self.assertEqual(etiqueta.con_src("NUEVO"), '<img src="NUEVO" alt=x>')

    def test_sin_reemplazos_el_documento_no_cambia(self):
        html = "<div><img src='a.png'></div>"
        self.assertEqual(reemplazar_etiquetas(html, {}), html)


class TestDetectarMime(unittest.TestCase):

    def test_por_firma_y_extension(self):
        self.assertEqual(detectar_mime(PNG, "sin_extension"), "image/png")
        self.assertEqual(detectar_mime(GIF, "x.png"), "image/gif")  # la firma prevalece
        self.assertEqual(detectar_mime(SVG, "logo"), "image/svg+xml")
        mimetypes.add_type("image/avif", ".avif")
        self.assertEqual(detectar_mime(b"sin firma conocida", "foto.avif"), "image/avif")
        with self.assertRaises(ErrorImagen):
            detectar_mime(b"texto con extension de imagen", "foto.jpg")
        with self.assertRaises(ErrorImagen):
            detectar_mime(b"esto es texto", "archivo.txt")

    def test_svg_con_encabezado_extenso(self):
        svg = b'<?xml version="1.0"?>\n<!-- ' + b"metadatos " * 500 + b"-->\n" + SVG
        self.assertEqual(detectar_mime(svg, "logo.svg"), "image/svg+xml")

    def test_html_con_svg_embebido_no_es_imagen(self):
        with self.assertRaises(ErrorImagen):
            detectar_mime(b"<!DOCTYPE html><html><body><svg></svg></body></html>", "x.svg")

    def test_tipo_declarado_por_el_servidor(self):
        self.assertEqual(detectar_mime(b"sin firma", "/imagen", "image/avif"), "image/avif")
        with self.assertRaises(ErrorImagen):
            detectar_mime(b"no es png", "/imagen", "image/png")


class _BaseTemporal(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def escribir(self, relativa: str, contenido: bytes | str) -> Path:
        ruta = self.raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenido, str):
            contenido = contenido.encode("utf-8")
        ruta.write_bytes(contenido)
        return ruta


class TestBuscadorHtml(_BaseTemporal):

    def test_archivos_y_directorios_recursivos(self):
        a = self.escribir("a.html", "")
        b = self.escribir("sub/profundo/b.HTM", "")
        self.escribir("sub/nota.txt", "")
        self.escribir("sub/b_base64.html", "")  # salida previa: se ignora
        archivos, descartados = BuscadorHtml(excluir_sufijo="_base64").buscar(
            [self.raiz, a, self.raiz / "no_existe"])
        self.assertEqual(archivos, [a.resolve(), b.resolve()])
        self.assertEqual(descartados, [(self.raiz / "no_existe", "La ruta no existe")])

    def test_entradas_explicitas_descartadas_se_informan(self):
        nota = self.escribir("nota.txt", "")
        previa = self.escribir("p_base64.html", "")
        _, descartados = BuscadorHtml(excluir_sufijo="_base64").buscar([nota, previa])
        self.assertEqual([ruta for ruta, _ in descartados], [nota, previa])
        self.assertIn("No es un archivo HTML", descartados[0][1])
        self.assertIn("ejecución anterior", descartados[1][1])


class TestProcesamiento(_BaseTemporal):

    def test_flujo_completo(self):
        self.escribir("img/logo.png", PNG)
        self.escribir("sitio/sub/icono.gif", GIF)
        self.escribir("sitio/sub/no_imagen.png", b"texto plano")
        original = (
            "<html><body>\n"
            "<img src=\"../img/logo.png\">\n"
            "<img src='sub/icono.gif?v=3'>\n"
            "<img src=\"sub/no_imagen.png\">\n"
            "<img src=\"falta.png\">\n"
            "<img src=\"../img/logo.png\">\n"
            f"<img src=\"{DATA_PNG}\">\n"
            "<img alt=\"sin src\">\n"
            "<img src=\"ftp://servidor/x.png\">\n"
            "</body></html>"
        )
        html = self.escribir("sitio/pagina.html", original)

        reporte = ejecutar([self.raiz / "sitio"], permitir_remotas=False)
        clave = str(html.resolve())

        self.assertEqual(reporte.a_dict()["success"], {clave: ["../img/logo.png", "sub/icono.gif?v=3"]})
        fallidas = {f["src"]: f["error"] for f in reporte.a_dict()["fail"][clave]}
        self.assertEqual(set(fallidas), {"sub/no_imagen.png", "falta.png", None, "ftp://servidor/x.png"})
        self.assertIn("No existe", fallidas["falta.png"])

        # El original no se modifica y se genera un archivo nuevo.
        self.assertEqual(html.read_text(encoding="utf-8"), original)
        generado = (self.raiz / "sitio" / "pagina_base64.html").read_text(encoding="utf-8")
        self.assertEqual(generado.count(DATA_PNG), 3)  # 2 reemplazos de logo + la ya embebida
        self.assertIn("data:image/gif;base64,", generado)
        self.assertIn('src="falta.png"', generado)

    def test_directorio_de_salida_replica_estructura(self):
        self.escribir("entrada/a/uno.html", "<img src='x.png'>")
        self.escribir("entrada/a/x.png", PNG)
        self.escribir("entrada/b/dos.html", "<p>sin imágenes</p>")
        salida = self.raiz / "salida"

        reporte = ejecutar([self.raiz / "entrada"], salida=salida, sufijo="", permitir_remotas=False)

        self.assertTrue((salida / "a" / "uno.html").exists())
        self.assertTrue((salida / "b" / "dos.html").exists())
        self.assertEqual(reporte.total_exitos, 1)
        self.assertEqual(reporte.fail, {})

    def test_conserva_codificacion_y_saltos_de_linea(self):
        self.escribir("x.png", PNG)
        html = self.escribir("latin.html", "<p>Café ñandú</p>\r\n<img src=x.png>\r\n".encode("cp1252"))
        ejecutar([html], permitir_remotas=False)
        generado = (self.raiz / "latin_base64.html").read_bytes()
        self.assertTrue(generado.startswith("<p>Café ñandú</p>\r\n".encode("cp1252")))
        self.assertTrue(generado.endswith(b">\r\n"))

    def test_ruta_inexistente_se_reporta(self):
        reporte = ejecutar([self.raiz / "no_existe.html"], permitir_remotas=False)
        self.assertEqual(list(reporte.fail), [str(self.raiz / "no_existe.html")])

    def test_nunca_sobrescribe_el_original(self):
        self.escribir("x.png", PNG)
        original = "<img src='x.png'>"
        html = self.escribir("p.html", original)
        reporte = ejecutar([self.raiz], salida=self.raiz, sufijo="", permitir_remotas=False)
        self.assertIn("sobrescribiría", reporte.fail[str(html.resolve())][0]["error"])
        self.assertEqual(html.read_text(encoding="utf-8"), original)

    def test_nunca_sobrescribe_otra_entrada(self):
        self.escribir("sitio/x.png", PNG)
        self.escribir("sitio/index.html", "<img src='x.png'>")
        blog = self.escribir("sitio/blog/index.html", "<p>blog</p>")
        # La salida de sitio/index.html sería justamente sitio/blog/index.html.
        reporte = ejecutar([self.raiz / "sitio"], salida=self.raiz / "sitio" / "blog", sufijo="",
                           permitir_remotas=False)
        clave = str((self.raiz / "sitio" / "index.html").resolve())
        self.assertIn("sobrescribiría", reporte.fail[clave][0]["error"])
        self.assertEqual(blog.read_text(encoding="utf-8"), "<p>blog</p>")

    def test_src_malformado_no_detiene_el_proceso(self):
        html = self.escribir("p.html", "<img src='http://[::1/x.png'><img src='otra.png'>")
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertEqual(len(reporte.fail[str(html.resolve())]), 2)
        self.assertTrue((self.raiz / "p_base64.html").exists())

    def test_url_relativa_al_protocolo_no_es_archivo_local(self):
        html = self.escribir("p.html", "<img src='//cdn.ejemplo.com/img/logo.png'>")
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertIn("no soportado", reporte.fail[str(html.resolve())][0]["error"])

    def test_barra_invertida_como_separador(self):
        self.escribir("img/x.png", PNG)
        html = self.escribir("p.html", "<img src='img\\x.png'>")
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertEqual(reporte.success[str(html.resolve())], ["img\\x.png"])

    def test_html_utf16_con_bom(self):
        self.escribir("x.png", PNG)
        html = self.escribir("u16.html", "﻿<p>ñandú</p><img src='x.png'>".encode("utf-16-le"))
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertEqual(reporte.total_exitos, 1)
        generado = (self.raiz / "u16_base64.html").read_bytes()
        self.assertTrue(generado.startswith(b"\xff\xfe"))
        self.assertIn(DATA_PNG, generado.decode("utf-16"))

    def test_si_no_se_puede_escribir_no_reporta_exitos(self):
        self.escribir("x.png", PNG)
        html = self.escribir("p.html", "<img src='x.png'>")
        (self.raiz / "p_base64.html").mkdir()  # la ruta de salida está ocupada por un directorio
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertEqual(reporte.success, {})
        self.assertIn("No se pudo escribir", reporte.fail[str(html.resolve())][0]["error"])

    def test_cli_guarda_reporte_json(self):
        self.escribir("x.png", PNG)
        html = self.escribir("p.html", "<img src='x.png'>")
        ruta_reporte = self.raiz / "reportes" / "reporte.json"  # la carpeta todavía no existe
        with contextlib.redirect_stdout(io.StringIO()):
            codigo = main([str(html), "--sin-remotas", "--reporte", str(ruta_reporte)])
        self.assertEqual(codigo, 0)
        self.assertIn('"success"', ruta_reporte.read_text(encoding="utf-8"))

    def test_cli_exige_salida_si_el_sufijo_es_vacio(self):
        html = self.escribir("p.html", "<p></p>")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([str(html), "--sufijo", ""])


class _ManejadorSilencioso(http.server.SimpleHTTPRequestHandler):
    solicitudes: list[str] = []

    def do_GET(self):
        type(self).solicitudes.append(self.path)
        super().do_GET()

    def log_message(self, *args):
        pass


class TestImagenesRemotas(_BaseTemporal):

    def setUp(self):
        super().setUp()
        self.escribir("servidor/logo.png", PNG)
        self.escribir("servidor/con espacio.png", PNG)
        self.escribir("servidor/falsa.png", b"no soy un png")
        self.escribir("servidor/pagina.html", "<html>no soy imagen</html>")
        _ManejadorSilencioso.solicitudes.clear()
        manejador = functools.partial(_ManejadorSilencioso, directory=str(self.raiz / "servidor"))
        self.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.servidor.server_port}"

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def test_descarga_y_errores_http(self):
        html = self.escribir("p.html", (
            f"<img src='{self.url}/logo.png'>"
            f"<img src='{self.url}/con espacio.png'>"
            f"<img src='{self.url}/no_existe.png'>"
            f"<img src='{self.url}/pagina.html'>"
            f"<img src='{self.url}/falsa.png'>"
        ))
        reporte = ejecutar([html], timeout=5)
        clave = str(html.resolve())
        self.assertEqual(reporte.success[clave], [f"{self.url}/logo.png", f"{self.url}/con espacio.png"])
        errores = {f["src"]: f["error"] for f in reporte.fail[clave]}
        self.assertIn("HTTP 404", errores[f"{self.url}/no_existe.png"])
        self.assertIn("no una imagen", errores[f"{self.url}/pagina.html"])
        self.assertIn("no corresponde a un archivo image/png", errores[f"{self.url}/falsa.png"])

    def test_misma_url_se_descarga_una_sola_vez(self):
        url = f"{self.url}/logo.png"
        uno = self.escribir("a/uno.html", f"<img src='{url}'>")
        dos = self.escribir("b/dos.html", f"<img src='{url}'>")
        reporte = ejecutar([uno, dos], timeout=5)
        self.assertEqual(reporte.total_exitos, 2)
        self.assertEqual(_ManejadorSilencioso.solicitudes, ["/logo.png"])

    def test_remotas_deshabilitadas(self):
        html = self.escribir("p.html", f"<img src='{self.url}/logo.png'>")
        reporte = ejecutar([html], permitir_remotas=False)
        self.assertIn("no soportado", reporte.fail[str(html.resolve())][0]["error"])


if __name__ == "__main__":
    unittest.main()
