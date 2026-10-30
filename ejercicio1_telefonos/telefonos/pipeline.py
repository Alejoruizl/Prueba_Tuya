"""Pipeline Bronze -> Silver -> Gold con quality gates.

Lee las fuentes en CSV, valida, elige el teléfono principal y escribe la salida
solo si los quality gates pasan. Si alguno falla, no se publica y el proceso
termina con error: los consumidores siguen usando el último lote bueno.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .reglas import Cliente, Rechazo, RegistroCrudo, ValidadorTelefonos
from .supervivencia import ResultadoContacto, Supervivencia, TelefonoGold


@dataclass(frozen=True)
class ResultadoGate:
    gate: str
    valor: float
    umbral: float
    pasa: bool


@dataclass
class ResultadoCorrida:
    gold: list[TelefonoGold]
    cuarentena: list[Rechazo]
    gates: list[ResultadoGate]

    @property
    def publicable(self) -> bool:
        return all(g.pasa for g in self.gates)


def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def leer_fuentes(directorio: Path) -> list[RegistroCrudo]:
    """Cada archivo de fuentes/ es una fuente; su nombre identifica el origen."""
    crudos = []
    for archivo in sorted(directorio.glob("*.csv")):
        for i, fila in enumerate(_leer_csv(archivo), start=2):
            crudos.append(RegistroCrudo(fila["cliente_id"].strip(), fila["telefono"], archivo.stem,
                                        date.fromisoformat(fila["fecha_actualizacion"]), i))
    return crudos


def leer_clientes(ruta: Path) -> dict[str, Cliente]:
    return {f["cliente_id"]: Cliente(f["cliente_id"], f["ciudad"], f["autoriza_contacto"].upper() == "SI")
            for f in _leer_csv(ruta)}


def leer_contactos(ruta: Path) -> list[ResultadoContacto]:
    return [ResultadoContacto(f["telefono_e164"], date.fromisoformat(f["fecha"]), f["resultado"])
            for f in _leer_csv(ruta)]


def evaluar_gates(gold: list[TelefonoGold], cuarentena: list[Rechazo], total: int,
                  clientes: dict[str, Cliente], config: dict) -> list[ResultadoGate]:
    umbrales = config["quality_gates"]
    tasa_cuarentena = len(cuarentena) / total if total else 0.0
    principales = [g for g in gold if g.es_principal]
    duplicados = len(principales) - len({(g.cliente_id, g.tipo) for g in principales})
    con_movil = {g.cliente_id for g in principales if g.tipo.value == "MOVIL"}
    cobertura = len(con_movil) / len(clientes) if clientes else 0.0
    return [
        ResultadoGate("volumen_minimo", total, umbrales["volumen_minimo"], total >= umbrales["volumen_minimo"]),
        ResultadoGate("tasa_cuarentena_maxima", round(tasa_cuarentena, 4), umbrales["tasa_cuarentena_maxima"],
                      tasa_cuarentena <= umbrales["tasa_cuarentena_maxima"]),
        ResultadoGate("unicidad_principal", duplicados, 0, duplicados == 0),
        ResultadoGate("cobertura_movil_minima", round(cobertura, 4), umbrales["cobertura_movil_minima"],
                      cobertura >= umbrales["cobertura_movil_minima"]),
    ]


def ejecutar(directorio_datos: Path, fecha_corrida: date) -> ResultadoCorrida:
    config = json.loads((directorio_datos / "config.json").read_text(encoding="utf-8"))
    clientes = leer_clientes(directorio_datos / "clientes.csv")
    lista_negra = {f["telefono_e164"]: f["motivo"] for f in _leer_csv(directorio_datos / "lista_negra.csv")}
    contactos = leer_contactos(directorio_datos / "contactabilidad.csv")
    crudos = leer_fuentes(directorio_datos / "fuentes")

    validos, rechazos = ValidadorTelefonos(clientes, lista_negra).validar(crudos)
    gold = Supervivencia(config["supervivencia"], contactos, fecha_corrida).elegir(validos)
    gates = evaluar_gates(gold, rechazos, len(crudos), clientes, config)
    return ResultadoCorrida(gold, rechazos, gates)


def _escribir_csv(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]) if filas else ["sin_datos"])
        escritor.writeheader()
        escritor.writerows(filas)


def publicar(resultado: ResultadoCorrida, directorio_salida: Path, fecha_corrida: date) -> None:
    """Escribe cuarentena y reporte siempre; la tabla Gold solo si los gates pasan."""
    _escribir_csv(directorio_salida / "cuarentena.csv", [
        {"cliente_id": r.crudo.cliente_id, "telefono_original": r.crudo.telefono, "fuente": r.crudo.fuente,
         "fila_origen": r.crudo.fila_origen, "regla": r.regla, "motivo": r.motivo}
        for r in resultado.cuarentena])
    reporte = {"fecha_corrida": fecha_corrida.isoformat(), "publicado": resultado.publicable,
               "registros_gold": len(resultado.gold), "registros_cuarentena": len(resultado.cuarentena),
               "gates": [asdict(g) for g in resultado.gates]}
    (directorio_salida / "reporte_gates.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False),
                                                          encoding="utf-8")
    if resultado.publicable:
        filas = []
        for g in resultado.gold:
            fila = asdict(g)
            fila["tipo"] = g.tipo.value
            fila["id_lote"] = fecha_corrida.isoformat()
            filas.append({k: ("" if v is None else v) for k, v in fila.items()})
        _escribir_csv(directorio_salida / "dim_cliente_telefono.csv", filas)
