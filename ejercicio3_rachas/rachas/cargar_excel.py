"""Carga las hojas del Excel de rachas a las tablas de staging de SQLite."""

from __future__ import annotations

import datetime as dt
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook


@dataclass(frozen=True)
class HojaStaging:
    """Relación entre una hoja del Excel y su tabla de staging."""

    hoja: str
    tabla: str
    columnas: Sequence[str]


HOJAS = (
    HojaStaging("historia", "stg_historia", ("identificacion", "corte_mes", "saldo")),
    HojaStaging("retiros", "stg_retiros", ("identificacion", "fecha_retiro")),
)


class ErrorEstructuraExcel(ValueError):
    """El archivo no es un Excel válido o no tiene las hojas o columnas esperadas."""


def _a_valor_sql(valor: Any) -> Any:
    """Convierte fechas a ISO-8601; el resto se conserva para validarlo en SQL."""
    if isinstance(valor, dt.datetime):
        return valor.date().isoformat() if valor.time() == dt.time() else valor.isoformat(sep=" ")
    if isinstance(valor, dt.date):
        return valor.isoformat()
    return valor


def _leer_filas(libro: Workbook, hoja: HojaStaging) -> Iterator[tuple[Any, ...]]:
    if hoja.hoja not in libro.sheetnames:
        raise ErrorEstructuraExcel(f"No existe la hoja '{hoja.hoja}'")

    filas = libro[hoja.hoja].iter_rows(values_only=True)
    encabezado = [str(c).strip().lower() if c is not None else "" for c in next(filas, ())]
    faltantes = [c for c in hoja.columnas if c not in encabezado]
    if faltantes:
        raise ErrorEstructuraExcel(f"Hoja '{hoja.hoja}': faltan columnas {faltantes}")
    posiciones = [encabezado.index(c) for c in hoja.columnas]

    for numero_fila, fila in enumerate(filas, start=2):
        valores = [fila[i] if i < len(fila) else None for i in posiciones]
        if all(v is None for v in valores):
            continue  # filas vacías al final de la hoja
        yield (numero_fila, *map(_a_valor_sql, valores))


def cargar_staging(conexion: sqlite3.Connection, ruta_excel: Path) -> dict[str, int]:
    """Reemplaza el contenido de staging con el Excel y retorna filas cargadas por tabla.

    La carga es atómica: si una hoja no cumple la estructura, staging queda como estaba.
    """
    try:
        libro = load_workbook(ruta_excel, read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError) as error:
        raise ErrorEstructuraExcel(f"{ruta_excel.name} no es un archivo Excel válido: {error}") from None

    conteos = {}
    try:
        with conexion:
            for hoja in HOJAS:
                conexion.execute(f"DELETE FROM {hoja.tabla}")
                columnas = ", ".join(("fila_origen", *hoja.columnas))
                marcadores = ", ".join("?" * (len(hoja.columnas) + 1))
                cursor = conexion.executemany(
                    f"INSERT INTO {hoja.tabla} ({columnas}) VALUES ({marcadores})",
                    _leer_filas(libro, hoja),
                )
                conteos[hoja.tabla] = cursor.rowcount
    finally:
        libro.close()
    return conteos
