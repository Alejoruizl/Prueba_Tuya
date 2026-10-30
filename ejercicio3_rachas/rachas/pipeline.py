"""Orquesta la construcción de la base de datos y la consulta de rachas."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .cargar_excel import cargar_staging

DIRECTORIO_SQL = Path(__file__).resolve().parent.parent / "sql"
SCRIPT_ESQUEMA = DIRECTORIO_SQL / "01_esquema.sql"
SCRIPT_CALIDAD = DIRECTORIO_SQL / "02_calidad_y_carga.sql"
CONSULTA_RACHAS = DIRECTORIO_SQL / "03_rachas.sql"


@dataclass(frozen=True)
class Racha:
    identificacion: str
    racha: int
    fecha_fin: str
    nivel: str


def _leer_sql(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.executescript(_leer_sql(SCRIPT_ESQUEMA))


def depurar(conexion: sqlite3.Connection) -> None:
    conexion.executescript(_leer_sql(SCRIPT_CALIDAD))


def construir_base(conexion: sqlite3.Connection, ruta_excel: Path) -> dict[str, int]:
    """Crea el esquema, carga el Excel a staging y aplica las reglas de calidad."""
    crear_esquema(conexion)
    conteos = cargar_staging(conexion, ruta_excel)
    depurar(conexion)
    return conteos


def calcular_rachas(conexion: sqlite3.Connection, fecha_base: dt.date, n: int) -> list[Racha]:
    if n < 1:
        raise ValueError("n debe ser un entero mayor o igual a 1")
    filas = conexion.execute(
        _leer_sql(CONSULTA_RACHAS),
        {"fecha_base": fecha_base.isoformat(), "n": n},
    ).fetchall()
    return [Racha(*fila) for fila in filas]


def resumen_calidad(conexion: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    return conexion.execute(
        """
        SELECT tabla, regla, severidad, COUNT(*) AS cantidad
        FROM dq_incidencias
        GROUP BY tabla, regla, severidad
        ORDER BY regla
        """
    ).fetchall()
