"""Normalización de números de teléfono colombianos al formato E.164 (+57XXXXXXXXXX).

Plan de numeración vigente (CRC):
- Móvil: 10 dígitos que empiezan por 3.
- Fijo: 10 dígitos que empiezan por 60 seguido del indicativo regional (marcación
  unificada desde 2021). Los fijos antiguos de 7 dígitos se completan con el
  indicativo de la ciudad del cliente cuando se conoce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

CODIGO_PAIS = "57"
LONGITUD_NACIONAL = 10

# Indicativo regional de la marcación fija unificada (60 + dígito)
INDICATIVO_POR_CIUDAD = {
    "BOGOTA": "1", "MEDELLIN": "4", "CALI": "2", "BARRANQUILLA": "5", "CARTAGENA": "5",
    "BUCARAMANGA": "7", "CUCUTA": "7", "PEREIRA": "6", "MANIZALES": "6", "ARMENIA": "6",
    "IBAGUE": "8", "NEIVA": "8", "VILLAVICENCIO": "8", "PASTO": "2", "POPAYAN": "2",
    "SANTA MARTA": "5", "VALLEDUPAR": "5", "MONTERIA": "4", "SINCELEJO": "5", "TUNJA": "8",
}

_NO_DIGITOS = re.compile(r"\D")
_TILDES = str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")


class TipoTelefono(str, Enum):
    MOVIL = "MOVIL"
    FIJO = "FIJO"


@dataclass(frozen=True)
class TelefonoNormalizado:
    e164: str
    tipo: TipoTelefono
    nacional: str  # los 10 dígitos sin código de país


class ErrorNormalizacion(ValueError):
    """El valor no se puede llevar a un número colombiano válido."""


def _normalizar_ciudad(ciudad: str | None) -> str:
    return (ciudad or "").strip().upper().translate(_TILDES)


def _a_digitos_nacionales(valor: str, ciudad: str | None) -> str:
    """Quita formato, prefijos internacionales y de larga distancia; completa fijos antiguos."""
    digitos = _NO_DIGITOS.sub("", valor)
    if not digitos:
        raise ErrorNormalizacion("Sin dígitos")

    if digitos.startswith("00" + CODIGO_PAIS):        # 0057 300 ...
        digitos = digitos[2 + len(CODIGO_PAIS):]
    elif digitos.startswith(CODIGO_PAIS) and len(digitos) == LONGITUD_NACIONAL + len(CODIGO_PAIS):
        digitos = digitos[len(CODIGO_PAIS):]           # 57 300 ... o +57 300 ...
    elif digitos.startswith("0") and len(digitos) == LONGITUD_NACIONAL + 1:
        digitos = digitos[1:]                          # 0 + número nacional (marcación antigua)

    if len(digitos) == 7:                              # fijo antiguo sin indicativo
        indicativo = INDICATIVO_POR_CIUDAD.get(_normalizar_ciudad(ciudad))
        if indicativo is None:
            raise ErrorNormalizacion("Fijo de 7 dígitos sin ciudad conocida para completar el indicativo")
        digitos = "60" + indicativo + digitos
    return digitos


def normalizar(valor: str | None, ciudad: str | None = None) -> TelefonoNormalizado:
    """Convierte un teléfono en cualquier formato a E.164, o lanza ErrorNormalizacion."""
    if valor is None or not str(valor).strip():
        raise ErrorNormalizacion("Teléfono vacío")

    nacional = _a_digitos_nacionales(str(valor), ciudad)
    if len(nacional) != LONGITUD_NACIONAL:
        raise ErrorNormalizacion(f"Longitud inválida: {len(nacional)} dígitos")
    if nacional.startswith("3"):
        tipo = TipoTelefono.MOVIL
    elif nacional.startswith("60") and nacional[2] in "12345678":
        tipo = TipoTelefono.FIJO
    else:
        raise ErrorNormalizacion("Prefijo no corresponde a móvil (3) ni a fijo (60X)")
    return TelefonoNormalizado(f"+{CODIGO_PAIS}{nacional}", tipo, nacional)
