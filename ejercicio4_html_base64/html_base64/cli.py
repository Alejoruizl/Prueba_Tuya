"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from .descubrimiento import BuscadorHtml
from .fuentes import FuenteArchivoLocal, FuenteHttp, FuenteImagen
from .procesador import SUFIJO_POR_DEFECTO, DestinoSalida, ProcesadorHtml
from .reporte import ReporteProcesamiento


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="html_base64",
        description="Incrusta en base64 las imágenes <img> de archivos HTML, generando archivos nuevos.",
    )
    parser.add_argument("rutas", nargs="+", type=Path,
                        help="Archivos HTML y/o directorios (se recorren recursivamente)")
    parser.add_argument("-o", "--salida", type=Path,
                        help="Directorio de salida (replica la estructura). Por defecto, junto al original")
    parser.add_argument("--sufijo", default=SUFIJO_POR_DEFECTO,
                        help=f"Sufijo del archivo generado (por defecto '{SUFIJO_POR_DEFECTO}')")
    parser.add_argument("--reporte", type=Path, help="Ruta para guardar el objeto resultado en JSON")
    parser.add_argument("--sin-remotas", action="store_true", help="No descargar imágenes http(s)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout de descarga en segundos")
    args = parser.parse_args(argv)

    if not args.sufijo and args.salida is None:
        parser.error("con --sufijo vacío es obligatorio --salida, para no sobrescribir los originales")
    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que 0")
    return args


def ejecutar(rutas: Iterable[str | Path], salida: Path | None = None,
             sufijo: str = SUFIJO_POR_DEFECTO, permitir_remotas: bool = True,
             timeout: float = 10.0) -> ReporteProcesamiento:
    """Punto de entrada programático: retorna el objeto ``{success, fail}``."""
    archivos, descartados = BuscadorHtml(excluir_sufijo=sufijo or None).buscar(rutas)

    fuentes: list[FuenteImagen] = [FuenteArchivoLocal()]
    if permitir_remotas:
        fuentes.append(FuenteHttp(timeout=timeout))
    destino = DestinoSalida(sufijo, salida, DestinoSalida.raiz_comun(archivos))

    reporte = ProcesadorHtml(fuentes, destino).procesar(archivos)
    for ruta, motivo in descartados:
        reporte.registrar_fallo(str(ruta), None, motivo)
    return reporte


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    reporte = ejecutar(args.rutas, args.salida, args.sufijo, not args.sin_remotas, args.timeout)

    print(reporte.a_json())
    print(f"\nArchivos generados: {len(reporte.generados)} | "
          f"imágenes exitosas: {reporte.total_exitos} | fallidas: {reporte.total_fallos}")
    for original, generado in reporte.generados.items():
        print(f"  {original} -> {generado}")

    if args.reporte:
        args.reporte.parent.mkdir(parents=True, exist_ok=True)
        args.reporte.write_text(reporte.a_json(), encoding="utf-8")
    return 1 if reporte.total_fallos else 0
