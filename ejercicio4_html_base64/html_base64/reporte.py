"""Objeto resultado con las imágenes procesadas con éxito y las que fallaron."""

from __future__ import annotations

import json
from typing import Any


class ReporteProcesamiento:
    """Acumula resultados por archivo HTML.

    Estructura de ``a_dict()``::

        {
            "success": {"ruta/archivo.html": ["img/logo.png", ...]},
            "fail":    {"ruta/archivo.html": [{"src": "x.png", "error": "..."}]}
        }
    """

    def __init__(self) -> None:
        self.success: dict[str, list[str]] = {}
        self.fail: dict[str, list[dict[str, Any]]] = {}
        self.generados: dict[str, str] = {}

    def registrar_exito(self, html: str, src: str) -> None:
        self.success.setdefault(html, []).append(src)

    def registrar_fallo(self, html: str, src: str | None, error: str) -> None:
        self.fail.setdefault(html, []).append({"src": src, "error": error})

    def registrar_salida(self, html: str, salida: str) -> None:
        self.generados[html] = salida

    @property
    def total_exitos(self) -> int:
        return sum(map(len, self.success.values()))

    @property
    def total_fallos(self) -> int:
        return sum(map(len, self.fail.values()))

    def a_dict(self) -> dict[str, dict[str, list[Any]]]:
        return {"success": self.success, "fail": self.fail}

    def a_json(self, indent: int = 2) -> str:
        return json.dumps(self.a_dict(), indent=indent, ensure_ascii=False)
