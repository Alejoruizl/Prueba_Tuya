"""Reglas de validación por registro (T01 a T06 del documento de diseño).

Cada regla devuelve None si el registro la cumple, o el motivo del incumplimiento.
Las reglas de rechazo mandan el registro a cuarentena; las de marcado lo dejan pasar
con una bandera.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from .normalizacion import ErrorNormalizacion, TelefonoNormalizado, TipoTelefono, normalizar


@dataclass(frozen=True)
class RegistroCrudo:
    """Un teléfono tal como llega de una fuente (capa Bronze)."""

    cliente_id: str
    telefono: str
    fuente: str
    fecha_actualizacion: date
    fila_origen: int


@dataclass
class RegistroValidado:
    """Un teléfono normalizado con el resultado de las reglas (capa Silver)."""

    crudo: RegistroCrudo
    telefono: TelefonoNormalizado
    marcas: list[str] = field(default_factory=list)

    @property
    def cliente_id(self) -> str:
        return self.crudo.cliente_id

    @property
    def e164(self) -> str:
        return self.telefono.e164


@dataclass(frozen=True)
class Rechazo:
    crudo: RegistroCrudo
    regla: str
    motivo: str


@dataclass(frozen=True)
class Cliente:
    cliente_id: str
    ciudad: str
    autoriza_contacto: bool


# Patrones de números basura (T02): un solo dígito repetido o secuencias
_SECUENCIAS = ("0123456789", "1234567890", "9876543210")


def es_numero_basura(nacional: str) -> bool:
    cuerpo = nacional[1:] if nacional.startswith("3") else nacional[3:]
    if len(set(cuerpo)) == 1:                  # 3000000000, 3111111111
        return True
    return any(cuerpo in s for s in _SECUENCIAS)


ReglaRegistro = Callable[[RegistroValidado], str | None]


class ValidadorTelefonos:
    """Aplica las reglas a los registros crudos y separa válidos de rechazados."""

    def __init__(self, clientes: dict[str, Cliente], lista_negra: dict[str, str]) -> None:
        self._clientes = clientes
        self._lista_negra = lista_negra

    # --- reglas de rechazo -------------------------------------------------
    def _t02_basura(self, r: RegistroValidado) -> str | None:
        if es_numero_basura(r.telefono.nacional):
            return "Número basura (dígito repetido o secuencia)"
        return None

    def _t03_lista_negra(self, r: RegistroValidado) -> str | None:
        motivo = self._lista_negra.get(r.e164)
        return f"En lista negra: {motivo}" if motivo else None

    def _t05_cliente_existe(self, r: RegistroValidado) -> str | None:
        if r.cliente_id not in self._clientes:
            return "El cliente no existe en el maestro"
        return None

    # --- reglas de marcado ---------------------------------------------------
    def _t06_autorizacion(self, r: RegistroValidado) -> str | None:
        if not self._clientes[r.cliente_id].autoriza_contacto:
            return "SIN_AUTORIZACION"
        return None

    def validar(self, crudos: Iterable[RegistroCrudo]) -> tuple[list[RegistroValidado], list[Rechazo]]:
        validos: list[RegistroValidado] = []
        rechazos: list[Rechazo] = []
        rechazo = (("T05_CLIENTE_INEXISTENTE", self._t05_cliente_existe),
                   ("T02_NUMERO_BASURA", self._t02_basura),
                   ("T03_LISTA_NEGRA", self._t03_lista_negra))
        marcado = (("T06_SIN_AUTORIZACION", self._t06_autorizacion),)

        for crudo in crudos:
            cliente = self._clientes.get(crudo.cliente_id)
            try:
                telefono = normalizar(crudo.telefono, cliente.ciudad if cliente else None)
            except ErrorNormalizacion as error:   # T01: formato, longitud y prefijo
                rechazos.append(Rechazo(crudo, "T01_FORMATO_INVALIDO", str(error)))
                continue

            registro = RegistroValidado(crudo, telefono)
            motivo_rechazo = next(((codigo, m) for codigo, regla in rechazo if (m := regla(registro))), None)
            if motivo_rechazo:
                rechazos.append(Rechazo(crudo, *motivo_rechazo))
                continue
            registro.marcas = [codigo for codigo, regla in marcado if regla(registro)]
            validos.append(registro)

        self._t04_compartidos(validos)
        return validos, rechazos

    @staticmethod
    def _t04_compartidos(validos: list[RegistroValidado], maximo_clientes: int = 2) -> None:
        """Marca los números que comparten más de `maximo_clientes` clientes distintos."""
        clientes_por_numero: dict[str, set[str]] = {}
        for r in validos:
            clientes_por_numero.setdefault(r.e164, set()).add(r.cliente_id)
        for r in validos:
            if len(clientes_por_numero[r.e164]) > maximo_clientes:
                r.marcas.append("T04_TELEFONO_COMPARTIDO")


__all__ = ["Cliente", "RegistroCrudo", "RegistroValidado", "Rechazo", "ValidadorTelefonos",
           "TipoTelefono", "es_numero_basura"]
