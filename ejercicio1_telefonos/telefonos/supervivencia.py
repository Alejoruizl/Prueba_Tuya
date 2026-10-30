"""Elección del teléfono principal por cliente y tipo (golden record, capa Gold).

puntaje = peso_fuente + bono_verificado + recencia - penalizacion_rebote
Los pesos y bonos vienen de la configuración, no del código.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .reglas import RegistroValidado, TipoTelefono


@dataclass(frozen=True)
class ResultadoContacto:
    e164: str
    fecha: date
    resultado: str   # EFECTIVO, NO_ENTREGADO, NUMERO_ERRADO, BUZON


@dataclass(frozen=True)
class TelefonoGold:
    cliente_id: str
    telefono_e164: str
    tipo: TipoTelefono
    es_principal: bool
    puntaje_confianza: float
    fuente_origen: str
    fecha_actualizacion: date
    fecha_ultima_verificacion: date | None
    apto_contacto: bool
    marcas: str


class Supervivencia:

    def __init__(self, config: dict, contactos: list[ResultadoContacto], fecha_corrida: date) -> None:
        self._pesos = config["peso_fuente"]
        self._bono_verificado = config["bono_verificado"]
        self._dias_recencia = config["dias_recencia"]
        self._penalizacion_rebote = config["penalizacion_rebote"]
        self._fecha = fecha_corrida
        self._verificacion: dict[str, date] = {}
        self._rebotes: dict[str, int] = {}
        for c in contactos:
            if c.resultado == "EFECTIVO":
                self._verificacion[c.e164] = max(c.fecha, self._verificacion.get(c.e164, c.fecha))
            else:
                self._rebotes[c.e164] = self._rebotes.get(c.e164, 0) + 1

    def puntaje(self, r: RegistroValidado) -> float:
        peso = self._pesos.get(r.crudo.fuente, 0.0)
        verificado = self._bono_verificado if r.e164 in self._verificacion else 0.0
        antiguedad = (self._fecha - r.crudo.fecha_actualizacion).days
        recencia = max(0.0, 1 - antiguedad / self._dias_recencia) * 0.2
        rebote = self._penalizacion_rebote * self._rebotes.get(r.e164, 0)
        return round(peso + verificado + recencia - rebote, 4)

    def elegir(self, validos: list[RegistroValidado]) -> list[TelefonoGold]:
        """Un registro por cliente y número; el de mayor puntaje por tipo es el principal."""
        mejor: dict[tuple[str, str], tuple[float, RegistroValidado]] = {}
        for r in validos:                      # el mismo número puede venir de varias fuentes
            clave = (r.cliente_id, r.e164)
            p = self.puntaje(r)
            if clave not in mejor or p > mejor[clave][0]:
                mejor[clave] = (p, r)

        gold: list[TelefonoGold] = []
        por_cliente_tipo: dict[tuple[str, TipoTelefono], list[tuple[float, RegistroValidado]]] = {}
        for p, r in mejor.values():
            por_cliente_tipo.setdefault((r.cliente_id, r.telefono.tipo), []).append((p, r))

        for (cliente_id, tipo), candidatos in por_cliente_tipo.items():
            candidatos.sort(key=lambda x: (-x[0], -x[1].crudo.fecha_actualizacion.toordinal(), x[1].e164))
            for posicion, (p, r) in enumerate(candidatos):
                gold.append(TelefonoGold(
                    cliente_id=cliente_id, telefono_e164=r.e164, tipo=tipo,
                    es_principal=posicion == 0, puntaje_confianza=p,
                    fuente_origen=r.crudo.fuente, fecha_actualizacion=r.crudo.fecha_actualizacion,
                    fecha_ultima_verificacion=self._verificacion.get(r.e164),
                    apto_contacto="T06_SIN_AUTORIZACION" not in r.marcas,
                    marcas=";".join(sorted(set(r.marcas))),
                ))
        return sorted(gold, key=lambda g: (g.cliente_id, g.tipo.value, not g.es_principal, g.telefono_e164))
