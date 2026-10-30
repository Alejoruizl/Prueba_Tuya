"""Localización y reemplazo de etiquetas ``<img>`` preservando el resto del documento.

Se usa ``html.parser`` para identificar las etiquetas (ignora correctamente
comentarios, ``<script>`` y ``<style>``) y se reemplaza únicamente el valor del
atributo ``src`` dentro del texto original de cada etiqueta, así el HTML
generado es idéntico al original salvo por las imágenes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Mapping

# Atributo de una etiqueta con las mismas reglas de html.parser (y de HTML5): el valor
# va entre comillas dobles, simples o sin comillas hasta un espacio o '>'.
_ATRIBUTO = re.compile(
    r"""(?P<nombre>[^\t\n\r\f />][^\t\n\r\f /=>]*)"""
    r"""(?:[\t\n\r\f ]*=[\t\n\r\f ]*(?P<valor>"[^"]*"|'[^']*'|(?!["'])[^\t\n\r\f >]+))?"""
)
_NOMBRE_ETIQUETA = re.compile(r"<[^\t\n\r\f />]+")


@dataclass(frozen=True)
class EtiquetaImg:
    inicio: int       # posición del '<' en el documento
    texto: str        # texto original de la etiqueta de apertura
    src: str | None   # valor del atributo src, con entidades HTML ya resueltas

    @property
    def fin(self) -> int:
        return self.inicio + len(self.texto)

    def con_src(self, nuevo_src: str) -> str:
        """Retorna el texto de la etiqueta con el valor de ``src`` sustituido."""
        posicion = _NOMBRE_ETIQUETA.match(self.texto).end()
        for atributo in _ATRIBUTO.finditer(self.texto, posicion):
            if atributo.group("nombre").lower() == "src" and atributo.group("valor") is not None:
                inicio, fin = atributo.span("valor")
                return f'{self.texto[:inicio]}"{nuevo_src}"{self.texto[fin:]}'
        raise ValueError(f"No se encontró el atributo src en {self.texto}")


class _ParserImg(HTMLParser):

    def __init__(self, documento: str) -> None:
        super().__init__(convert_charrefs=True)
        self._inicios_linea = [0] + [m.end() for m in re.finditer("\n", documento)]
        self.etiquetas: list[EtiquetaImg] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        linea, columna = self.getpos()
        src = next((valor for nombre, valor in attrs if nombre == "src"), None)
        self.etiquetas.append(
            EtiquetaImg(self._inicios_linea[linea - 1] + columna, self.get_starttag_text(), src)
        )


def extraer_imagenes(documento: str) -> list[EtiquetaImg]:
    parser = _ParserImg(documento)
    parser.feed(documento)
    parser.close()
    return parser.etiquetas


def reemplazar_etiquetas(documento: str, reemplazos: Mapping[EtiquetaImg, str]) -> str:
    """Construye un nuevo documento sustituyendo cada etiqueta: ``{etiqueta: texto_nuevo}``."""
    partes: list[str] = []
    cursor = 0
    for etiqueta in sorted(reemplazos, key=lambda e: e.inicio):
        partes.append(documento[cursor:etiqueta.inicio])
        partes.append(reemplazos[etiqueta])
        cursor = etiqueta.fin
    partes.append(documento[cursor:])
    return "".join(partes)
