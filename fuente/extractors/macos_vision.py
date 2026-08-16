"""Local macOS Vision OCR without installing a command line OCR engine.

The adapter is deliberately small and injectable. Production callers use the
framework through PyObjC when available; tests can provide a fake adapter and
exercise unavailable, empty and error outcomes without touching a real Vault.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from typing import Any


class OCRUnavailableError(RuntimeError):
    """The native OCR backend is not available on this machine."""


class OCRProcessingError(RuntimeError):
    """Vision or Quartz could not process the supplied document."""


class MacOSVisionOCR:
    """Run Vision OCR locally for images and rasterized PDF pages."""

    method = "macos_vision"

    def __init__(self, *, max_dimension: int = 2000) -> None:
        self.max_dimension = max_dimension
        self._runtime: tuple[Any, ...] | None = None

    def available(self) -> bool:
        try:
            self._load_runtime()
        except OCRUnavailableError:
            return False
        return True

    def extract_image(self, path: Path) -> str:
        runtime = self._load_runtime()
        image = self._image_from_path(path, runtime)
        return self._recognize(image, runtime)

    def extract_pdf(self, path: Path) -> str:
        runtime = self._load_runtime()
        quartz = runtime[3]
        foundation = runtime[1]
        url = foundation.NSURL.fileURLWithPath_(str(path))
        document = quartz.CGPDFDocumentCreateWithURL(url)
        if document is None:
            raise OCRProcessingError(f"Quartz no pudo abrir {path.name}")

        page_count = quartz.CGPDFDocumentGetNumberOfPages(document)
        if not page_count:
            raise OCRProcessingError(f"El PDF {path.name} no tiene páginas")

        text: list[str] = []
        for index in range(1, page_count + 1):
            page = quartz.CGPDFDocumentGetPage(document, index)
            image = self._render_pdf_page(page, runtime)
            page_text = self._recognize(image, runtime).strip()
            if page_text:
                text.append(f"<!-- Página {index} -->\n{page_text}")
        return "\n\n".join(text)

    def _load_runtime(self) -> tuple[Any, ...]:
        if self._runtime is not None:
            return self._runtime
        if sys.platform != "darwin":
            raise OCRUnavailableError("Vision OCR solo está disponible en macOS")
        try:
            import objc
            import Foundation
            from Foundation import NSData
            import Quartz
        except Exception as error:  # pragma: no cover - platform dependent
            raise OCRUnavailableError(f"PyObjC/Quartz no disponible: {error}") from error

        try:
            bundle = Foundation.NSBundle.bundleWithPath_("/System/Library/Frameworks/Vision.framework")
            if bundle is None or not bundle.load():
                raise OCRUnavailableError("Vision.framework no se pudo cargar")
            request_class = objc.lookUpClass("VNRecognizeTextRequest")
            handler_class = objc.lookUpClass("VNImageRequestHandler")
            # objc.lookUpClass bypasses the generated Vision Python wrapper, so
            # register the NSError out-parameter explicitly.
            objc.registerMetaDataForSelector(
                b"VNImageRequestHandler",
                b"performRequests:error:",
                {"retval": {"type": "Z"}, "arguments": {3: {"type_modifier": b"o"}}},
            )
        except OCRUnavailableError:
            raise
        except Exception as error:  # pragma: no cover - platform dependent
            raise OCRUnavailableError(f"Vision.framework no expone OCR: {error}") from error

        self._runtime = (request_class, Foundation, NSData, Quartz, handler_class)
        return self._runtime

    def _image_from_path(self, path: Path, runtime: tuple[Any, ...]) -> Any:
        _request, foundation, NSData, quartz, _handler = runtime
        try:
            from PIL import Image

            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail((self.max_dimension, self.max_dimension))
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=92)
            raw = buffer.getvalue()
            data = NSData.dataWithBytes_length_(raw, len(raw))
            image_source = quartz.CGImageSourceCreateWithData(data, None)
        except Exception as error:
            raise OCRProcessingError(f"No se pudo preparar la imagen {path.name}: {error}") from error
        image = quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
        if image is None:
            raise OCRProcessingError(f"Quartz no pudo decodificar la imagen {path.name}")
        return image

    def _render_pdf_page(self, page: Any, runtime: tuple[Any, ...]) -> Any:
        _request, _foundation, _data, quartz, _handler = runtime
        try:
            box = quartz.CGPDFPageGetBoxRect(page, quartz.kCGPDFMediaBox)
            width = max(1.0, float(quartz.CGRectGetWidth(box)))
            height = max(1.0, float(quartz.CGRectGetHeight(box)))
            scale = min(1.0, self.max_dimension / max(width, height))
            pixel_width = max(1, int(width * scale))
            pixel_height = max(1, int(height * scale))
            color_space = quartz.CGColorSpaceCreateDeviceRGB()
            context = quartz.CGBitmapContextCreate(
                None,
                pixel_width,
                pixel_height,
                8,
                pixel_width * 4,
                color_space,
                quartz.kCGImageAlphaPremultipliedLast,
            )
            if context is None:
                raise OCRProcessingError("Quartz no pudo crear el lienzo del PDF")
            quartz.CGContextSetRGBFillColor(context, 1, 1, 1, 1)
            quartz.CGContextFillRect(context, quartz.CGRectMake(0, 0, pixel_width, pixel_height))
            quartz.CGContextScaleCTM(context, scale, scale)
            quartz.CGContextDrawPDFPage(context, page)
            image = quartz.CGBitmapContextCreateImage(context)
        except OCRProcessingError:
            raise
        except Exception as error:
            raise OCRProcessingError(f"Quartz no pudo rasterizar la página PDF: {error}") from error
        if image is None:
            raise OCRProcessingError("Quartz devolvió una imagen PDF vacía")
        return image

    @staticmethod
    def _recognize(image: Any, runtime: tuple[Any, ...]) -> str:
        request_class, _foundation, _data, _quartz, handler_class = runtime
        request = request_class.alloc().init()
        request.setRecognitionLevel_(1)  # VNRequestTextRecognitionLevelAccurate
        request.setRecognitionLanguages_(["es-ES", "en-US"])
        request.setUsesLanguageCorrection_(True)
        handler = handler_class.alloc().initWithCGImage_options_(image, {})
        result = handler.performRequests_error_([request], None)
        if isinstance(result, tuple):
            ok, error = result
        else:  # pragma: no cover - older PyObjC metadata
            ok, error = result, None
        if not ok:
            detail = (
                str(error)
                if error is not None
                else "Vision devolvió false sin NSError; el backend no pudo crear un resultado OCR"
            )
            raise OCRProcessingError(detail)

        lines: list[str] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                value = candidates[0].string()
                if value and value.strip():
                    lines.append(str(value).strip())
        return "\n".join(lines)
