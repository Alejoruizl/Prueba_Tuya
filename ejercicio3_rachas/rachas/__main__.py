"""CLI: python -m rachas --fecha-base 2024-12-31 --n 3"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sqlite3
import sys
from contextlib import closing
from dataclasses import astuple, fields
from pathlib import Path

from .cargar_excel import ErrorEstructuraExcel
from .pipeline import Racha, calcular_rachas, construir_base, resumen_calidad

RAIZ = Path(__file__).resolve().parent.parent


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rachas",
        description="Construye la base SQLite desde el Excel y calcula las rachas por nivel de deuda.",
    )
    parser.add_argument("--fecha-base", type=dt.date.fromisoformat, required=True,
                        help="Fecha de referencia YYYY-MM-DD")
    parser.add_argument("--n", type=int, required=True, help="Longitud mínima de la racha en meses")
    parser.add_argument("--excel", type=Path, default=RAIZ / "data" / "Rachas.xlsx")
    parser.add_argument("--db", type=Path, default=RAIZ / "rachas.db")
    parser.add_argument("--salida", type=Path, help="Ruta CSV opcional para guardar el resultado")
    parser.add_argument("--sin-recarga", action="store_true",
                        help="Usa la base existente sin volver a cargar el Excel")
    args = parser.parse_args(argv)

    if args.n < 1:
        parser.error("--n debe ser mayor o igual a 1")
    if args.sin_recarga and not args.db.is_file():
        parser.error(f"No existe la base {args.db}; ejecute primero sin --sin-recarga")
    if not args.sin_recarga and not args.excel.is_file():
        parser.error(f"No existe el archivo {args.excel}")
    return args


def _imprimir_calidad(incidencias: list[tuple[str, str, str, int]]) -> None:
    print("Incidencias de calidad de datos:")
    if not incidencias:
        print("  (ninguna)")
    for tabla, regla, severidad, cantidad in incidencias:
        print(f"  [{severidad:<11}] {tabla:<9} {regla:<38} {cantidad:>4}")
    print()


def _escribir_csv(ruta: Path, rachas: list[Racha]) -> None:
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow([f.name for f in fields(Racha)])
        escritor.writerows(astuple(r) for r in rachas)


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    with closing(sqlite3.connect(args.db)) as conexion:
        if not args.sin_recarga:
            try:
                conteos = construir_base(conexion, args.excel)
            except ErrorEstructuraExcel as error:
                print(f"rachas: error: {error}", file=sys.stderr)
                return 2
            print(f"Filas cargadas a staging: {conteos}\n")
            _imprimir_calidad(resumen_calidad(conexion))

        rachas = calcular_rachas(conexion, args.fecha_base, args.n)

    print(f"Rachas >= {args.n} meses con fecha_base {args.fecha_base}: {len(rachas)} clientes\n")
    print(f"{'identificacion':<20} {'racha':>5}  {'fecha_fin':<10}  nivel")
    for r in rachas:
        print(f"{r.identificacion:<20} {r.racha:>5}  {r.fecha_fin:<10}  {r.nivel}")

    if args.salida:
        _escribir_csv(args.salida, rachas)
        print(f"\nResultado guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
