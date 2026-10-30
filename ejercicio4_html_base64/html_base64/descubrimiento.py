"""Resolución de las rutas de entrada (archivos y/o directorios) a archivos HTML."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

EXTENSIONES_HTML = frozenset({".html", ".htm"})


class BuscadorHtml:
    """Expande archivos y directorios (recursivamente) a una lista única de HTML."""

    def __init__(self, extensiones: Iterable[str] = EXTENSIONES_HTML,
                 excluir_sufijo: str | None = None) -> None:
        self._extensiones = frozenset(e.lower() for e in extensiones)
        self._excluir_sufijo = excluir_sufijo

    def buscar(self, rutas: Iterable[str | Path]) -> tuple[list[Path], list[tuple[Path, str]]]:
        """Retorna (archivos_html, descartados).

        ``archivos_html`` no tiene duplicados y conserva un orden estable.
        ``descartados`` son las rutas indicadas explícitamente que no se procesarán,
        con el motivo, para que no desaparezcan del reporte sin explicación.
        """
        encontrados: dict[Path, None] = {}
        descartados: list[tuple[Path, str]] = []

        for ruta in map(Path, rutas):
            if ruta.is_dir():
                for archivo in sorted(p for p in ruta.rglob("*") if p.is_file()):
                    if self._motivo_exclusion(archivo) is None:
                        encontrados.setdefault(archivo.resolve(), None)
            elif ruta.is_file():
                motivo = self._motivo_exclusion(ruta)
                if motivo is None:
                    encontrados.setdefault(ruta.resolve(), None)
                else:
                    descartados.append((ruta, motivo))
            else:
                descartados.append((ruta, "La ruta no existe"))

        return list(encontrados), descartados

    def _motivo_exclusion(self, archivo: Path) -> str | None:
        if archivo.suffix.lower() not in self._extensiones:
            return "No es un archivo HTML (.html o .htm)"
        if self._excluir_sufijo and archivo.stem.endswith(self._excluir_sufijo):
            # Evita reprocesar las salidas de una ejecución anterior.
            return f"Es la salida de una ejecución anterior (sufijo '{self._excluir_sufijo}')"
        return None
