"""Fuentes de imágenes (estrategias) y codificación a data URI en base64.

Cada fuente sabe si puede atender un ``src`` y cómo obtener sus bytes. Para agregar
un origen nuevo (S3, por ejemplo) basta con implementar ``FuenteImagen``; el
procesador no se toca.
"""

from __future__ import annotations

import base64
import http.client
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Hashable

# Firmas binarias de los formatos de imagen más comunes.
_FIRMAS_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

# Formatos cuya firma se verifica: si la extensión o el servidor los declaran,
# el contenido debe coincidir.
_MIMES_VERIFICABLES = frozenset(
    {mime for _, mime in _FIRMAS_MIME}
    | {"image/bmp", "image/webp", "image/svg+xml", "image/vnd.microsoft.icon"}
)


class ErrorImagen(Exception):
    """No fue posible obtener o interpretar una imagen."""


@dataclass(frozen=True)
class Imagen:
    contenido: bytes
    mime: str

    def a_data_uri(self) -> str:
        codificado = base64.b64encode(self.contenido).decode("ascii")
        return f"data:{self.mime};base64,{codificado}"


def _es_svg(contenido: bytes) -> bool:
    """SVG: documento XML cuyo primer elemento es <svg> (excluye páginas HTML con SVG embebido)."""
    inicio = contenido[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return (inicio.startswith((b"<svg", b"<?xml", b"<!--", b"<!doctype svg"))
            and b"<html" not in inicio
            and b"<svg" in contenido.lower())


def detectar_mime(contenido: bytes, nombre: str = "", tipo_declarado: str | None = None) -> str:
    """Determina el tipo de imagen por su firma binaria.

    Si el contenido no tiene una firma conocida se usa el tipo declarado por el
    servidor o, en su defecto, la extensión del archivo (avif, heic, ...). Si ese
    tipo es uno de los que sí tienen firma (png, jpeg, ...), el archivo es inválido.
    """
    for firma, mime in _FIRMAS_MIME:
        if contenido.startswith(firma):
            return mime
    if contenido[:2] == b"BM" and contenido[6:10] == b"\x00\x00\x00\x00":
        return "image/bmp"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    if _es_svg(contenido):
        return "image/svg+xml"

    if tipo_declarado and tipo_declarado.startswith("image/"):
        mime = tipo_declarado
    else:
        mime, _ = mimetypes.guess_type(nombre)
    if mime in _MIMES_VERIFICABLES:
        raise ErrorImagen(f"El contenido no corresponde a un archivo {mime} válido")
    if mime and mime.startswith("image/"):
        return mime
    raise ErrorImagen("El contenido no corresponde a un formato de imagen reconocido")


def _esquema(src: str) -> str | None:
    """Esquema de la URL en minúsculas, o None si el ``src`` no es una URL válida."""
    try:
        return urllib.parse.urlsplit(src).scheme.lower()
    except ValueError:  # por ejemplo corchetes sin cerrar en el host: http://[::1
        return None


class FuenteImagen(ABC):

    @abstractmethod
    def soporta(self, src: str) -> bool:
        """Indica si esta fuente sabe resolver el ``src`` dado."""

    @abstractmethod
    def obtener(self, src: str, directorio_html: Path) -> Imagen:
        """Obtiene la imagen; las rutas relativas se resuelven contra ``directorio_html``."""

    def clave_cache(self, src: str, directorio_html: Path) -> Hashable:
        """Identifica la imagen para no leerla dos veces; por defecto depende del HTML."""
        return src, directorio_html


class FuenteArchivoLocal(FuenteImagen):
    """Rutas relativas, absolutas y URLs ``file://``."""

    def soporta(self, src: str) -> bool:
        if src.startswith("//"):  # relativa al protocolo (//cdn...): es una URL remota
            return False
        esquema = _esquema(src)
        # Una letra de unidad de Windows (C:\...) se interpreta como esquema de una letra.
        return esquema is not None and (esquema in ("", "file") or len(esquema) == 1)

    def obtener(self, src: str, directorio_html: Path) -> Imagen:
        try:
            ruta = self._resolver(src, directorio_html)
            contenido = ruta.read_bytes()
        except FileNotFoundError as error:
            raise ErrorImagen(f"No existe el archivo {error.filename or src}") from None
        except (OSError, ValueError) as error:  # ValueError: ruta con caracteres nulos
            motivo = getattr(error, "strerror", None) or error
            raise ErrorImagen(f"No se pudo leer {src}: {motivo}") from None
        return Imagen(contenido, detectar_mime(contenido, ruta.name))

    @staticmethod
    def _resolver(src: str, directorio_html: Path) -> Path:
        partes = urllib.parse.urlsplit(src)
        if partes.scheme.lower() == "file":
            return Path(urllib.request.url2pathname(partes.path))
        if len(partes.scheme) == 1:  # C:\ruta\imagen.png
            return Path(src)
        # Como en los navegadores, '\' se acepta como separador; se descartan query
        # string y fragmento (logo.png?v=2#x) y se decodifican los escapes (%20).
        ruta = Path(urllib.parse.unquote(partes.path.replace("\\", "/")))
        return ruta if ruta.is_absolute() else directorio_html / ruta


class FuenteHttp(FuenteImagen):
    """URLs ``http``, ``https`` y relativas al protocolo (``//cdn...``)."""

    def __init__(self, timeout: float = 10.0, max_bytes: int = 20 * 1024 * 1024) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def soporta(self, src: str) -> bool:
        return src.startswith("//") or _esquema(src) in ("http", "https")

    def clave_cache(self, src: str, directorio_html: Path) -> Hashable:
        return src  # una URL absoluta es la misma imagen desde cualquier HTML

    def obtener(self, src: str, directorio_html: Path) -> Imagen:
        url = f"https:{src}" if src.startswith("//") else src
        # Los navegadores toleran espacios y tildes en el src; urllib exige escaparlos.
        url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
        solicitud = urllib.request.Request(url, headers={"User-Agent": "html-base64/1.0"})
        try:
            with urllib.request.urlopen(solicitud, timeout=self._timeout) as respuesta:
                contenido = respuesta.read(self._max_bytes + 1)
                tipo_declarado = respuesta.headers.get_content_type()
        except urllib.error.HTTPError as error:
            error.close()
            raise ErrorImagen(f"HTTP {error.code} al descargar {url}") from None
        except (OSError, http.client.HTTPException, ValueError) as error:
            # OSError cubre URLError, timeouts y errores de conexión.
            motivo = getattr(error, "reason", None) or error
            raise ErrorImagen(f"No se pudo descargar {url}: {motivo}") from None

        if len(contenido) > self._max_bytes:
            raise ErrorImagen(f"La imagen supera el máximo permitido de {self._max_bytes} bytes")
        try:
            return Imagen(contenido, detectar_mime(contenido, urllib.parse.urlsplit(url).path,
                                                   tipo_declarado))
        except ErrorImagen:
            if not tipo_declarado.startswith("image/"):
                raise ErrorImagen(f"El servidor respondió '{tipo_declarado}', no una imagen") from None
            raise
