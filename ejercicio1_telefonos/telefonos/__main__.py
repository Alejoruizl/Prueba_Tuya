"""CLI: python -m telefonos [--datos data] [--salida salida] [--fecha 2026-10-30]

Termina con código 0 si el lote se publicó y 1 si algún quality gate falló.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .pipeline import ejecutar, publicar

RAIZ = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="telefonos",
                                     description="Construye el dataset de teléfonos de clientes con quality gates.")
    parser.add_argument("--datos", type=Path, default=RAIZ / "data")
    parser.add_argument("--salida", type=Path, default=RAIZ / "salida")
    parser.add_argument("--fecha", type=dt.date.fromisoformat, default=dt.date.today(),
                        help="Fecha de la corrida (afecta la recencia)")
    args = parser.parse_args(argv)

    resultado = ejecutar(args.datos, args.fecha)
    publicar(resultado, args.salida, args.fecha)

    print(f"Registros válidos: {len(resultado.gold)} | cuarentena: {len(resultado.cuarentena)}\n")
    print("Quality gates:")
    for g in resultado.gates:
        print(f"  [{'OK   ' if g.pasa else 'FALLA'}] {g.gate:<26} valor {g.valor:<8} umbral {g.umbral}")
    if resultado.publicable:
        print(f"\nLote publicado en {args.salida / 'dim_cliente_telefono.csv'}")
        return 0
    print("\nLote NO publicado: se conserva la versión anterior", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
