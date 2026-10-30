"""Orquestación: lectura de HTML, incrustación de imágenes y escritura del nuevo archivo."""

from __future__ import annotations

import codecs
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Hashable, Iterable, Sequence

from .fuentes import ErrorImagen, FuenteImagen, Imagen
from .html_img import EtiquetaImg, extraer_imagenes, reemplazar_etiquetas
from .reporte import ReporteProcesamiento

SUFIJO_POR_DEFECTO = "_base64"

# Marcas de orden de bytes (BOM). Se decodifica sin quitarlas para que el archivo
# generado las conserve. UTF-32 LE va antes que UTF-16 LE porque comparten prefijo.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


@dataclass(frozen=True)
class DocumentoHtml:
    texto: str
    codificacion: str

    @classmethod
    def leer(cls, ruta: Path) -> "DocumentoHtml":
        contenido = ruta.read_bytes()
        bom = next((codif for marca, codif in _BOMS if contenido.startswith(marca)), None)
        for codificacion in [bom] if bom else ["utf-8", "cp1252"]:
            try:
                return cls(contenido.decode(codificacion), codificacion)
            except UnicodeDecodeError:
                continue
        return cls(contenido.decode("latin-1"), "latin-1")  # latin-1 nunca falla

    def escribir(self, ruta: Path, texto: str) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Se escribe en bytes para conservar los saltos de línea originales.
        ruta.write_bytes(texto.encode(self.codificacion))


class DestinoSalida:
    """Calcula la ruta del archivo generado."""

    def __init__(self, sufijo: str = SUFIJO_POR_DEFECTO, directorio: Path | None = None,
                 raiz_entradas: Path | None = None) -> None:
        if not sufijo and directorio is None:
            raise ValueError("Sin sufijo es obligatorio un directorio de salida")
        self.sufijo = sufijo
        self._directorio = directorio
        self._raiz = raiz_entradas

    def ruta_para(self, original: Path) -> Path:
        nombre = f"{original.stem}{self.sufijo}{original.suffix}"
        if self._directorio is None:
            return original.with_name(nombre)
        if self._raiz is not None:
            relativa = original.parent.relative_to(self._raiz)
        else:
            # Sin raíz común (unidades distintas): se conserva la ruta completa para no
            # mezclar archivos homónimos.
            unidad = original.drive.strip(":\\/").replace("\\", "_") or "raiz"
            relativa = Path(unidad, *original.parent.parts[1:])
        return self._directorio / relativa / nombre

    @staticmethod
    def raiz_comun(archivos: Sequence[Path]) -> Path | None:
        """Directorio común a todas las entradas, para replicar la estructura en la salida."""
        if not archivos:
            return None
        try:
            return Path(os.path.commonpath([a.parent for a in archivos]))
        except ValueError:  # unidades distintas en Windows, por ejemplo
            return None


class ProcesadorHtml:
    """Reemplaza las imágenes ``<img src>`` de cada HTML por su versión en base64."""

    def __init__(self, fuentes: Sequence[FuenteImagen], destino: DestinoSalida) -> None:
        self._fuentes = fuentes
        self._destino = destino
        self._cache: dict[Hashable, Imagen | str] = {}  # imagen o mensaje de error
        self._entradas: set[Path] = set()

    def procesar(self, archivos: Iterable[Path]) -> ReporteProcesamiento:
        archivos = list(archivos)
        self._entradas = {a.resolve() for a in archivos}
        reporte = ReporteProcesamiento()
        for archivo in archivos:
            try:
                self.procesar_archivo(archivo, reporte)
            except Exception as error:  # un error inesperado en un archivo no detiene el lote
                reporte.registrar_fallo(str(archivo), None, f"Error inesperado: {error!r}")
        return reporte

    def procesar_archivo(self, archivo: Path, reporte: ReporteProcesamiento) -> None:
        clave = str(archivo)
        salida = self._destino.ruta_para(archivo)
        destino = salida.resolve()
        if destino == archivo.resolve() or destino in self._entradas:
            reporte.registrar_fallo(clave, None, f"La salida {salida} sobrescribiría un archivo de entrada")
            return
        try:
            documento = DocumentoHtml.leer(archivo)
        except OSError as error:
            reporte.registrar_fallo(clave, None, f"No se pudo leer el HTML: {error.strerror or error}")
            return

        reemplazos: dict[EtiquetaImg, str] = {}
        resultados: dict[str | None, str | None] = {}  # src -> error (None = éxito), sin repetir

        for etiqueta in extraer_imagenes(documento.texto):
            src = etiqueta.src.strip() if etiqueta.src is not None else None
            if src and src.lower().startswith("data:"):
                continue  # ya está embebida
            try:
                reemplazos[etiqueta] = etiqueta.con_src(self._obtener(src, archivo.parent).a_data_uri())
            except (ErrorImagen, ValueError) as error:
                resultados.setdefault(src, str(error))
            else:
                resultados.setdefault(src, None)

        try:
            documento.escribir(salida, reemplazar_etiquetas(documento.texto, reemplazos))
        except OSError as error:
            reporte.registrar_fallo(clave, None, f"No se pudo escribir {salida}: {error.strerror or error}")
            return

        reporte.registrar_salida(clave, str(salida))
        for src, error in resultados.items():
            if error is None:
                reporte.registrar_exito(clave, src)
            else:
                reporte.registrar_fallo(clave, src, error)

    def _obtener(self, src: str | None, directorio_html: Path) -> Imagen:
        if not src:
            raise ErrorImagen("La etiqueta <img> no tiene atributo src o está vacío")
        fuente = next((f for f in self._fuentes if f.soporta(src)), None)
        if fuente is None:
            raise ErrorImagen(f"Origen de imagen no soportado: {src}")

        clave = fuente.clave_cache(src, directorio_html)
        if clave not in self._cache:
            try:
                self._cache[clave] = fuente.obtener(src, directorio_html)
            except ErrorImagen as error:
                self._cache[clave] = str(error)
        resultado = self._cache[clave]
        if isinstance(resultado, str):
            raise ErrorImagen(resultado)
        return resultado
