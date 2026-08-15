from pathlib import Path
import logging

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def ensure_app_icon(assets_dir: Path) -> Path:
    """Asegura la presencia del icono oficial de alta definición Fuente en assets/."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    icon_png = assets_dir / "fuente_icon.png"
    icon_ico = assets_dir / "fuente_icon.ico"

    if not icon_png.exists():
        logger.warning(f"No se encontró {icon_png.name} en assets.")
        return assets_dir

    if HAS_PIL and (not icon_ico.exists() or icon_png.stat().st_mtime > icon_ico.stat().st_mtime):
        try:
            img = Image.open(icon_png)
            img_ico = img.resize((256, 256), Image.Resampling.LANCZOS)
            img_ico.save(icon_ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            logger.info(f"Icono ICO multirresolución actualizado en {icon_ico.name}")
        except Exception as e:
            logger.error(f"Error convirtiendo PNG a ICO: {e}")

    ensure_archive_icon(assets_dir)
    return icon_png


def ensure_archive_icon(assets_dir: Path) -> Path:
    """Genera el icono estilo 'archivador' para 'La Memoria de Fuente'."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    icon_png = assets_dir / "archive_icon.png"
    icon_ico = assets_dir / "archive_icon.ico"

    if not icon_png.exists() and HAS_PIL:
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Estructura exterior del mueble archivador
            draw.rounded_rectangle([40, 30, 472, 482], radius=32, fill=(30, 41, 59, 255), outline=(71, 85, 105, 255), width=6)

            # 3 cajones archivadores
            drawer_y_starts = [50, 190, 330]
            for y_start in drawer_y_starts:
                y_end = y_start + 120
                draw.rounded_rectangle([60, y_start, 452, y_end], radius=16, fill=(51, 65, 85, 255), outline=(100, 116, 139, 255), width=4)
                # Etiqueta blanca de archivador
                draw.rounded_rectangle([206, y_start + 18, 306, y_start + 46], radius=6, fill=(241, 245, 249, 255), outline=(148, 163, 184, 255), width=2)
                # Asa de tirar del cajón
                draw.rounded_rectangle([186, y_start + 65, 326, y_start + 85], radius=10, fill=(203, 213, 225, 255), outline=(148, 163, 184, 255), width=3)

            img.save(icon_png, "PNG")
            logger.info(f"Icono de archivador generado en {icon_png.name}")
        except Exception as e:
            logger.error(f"Error generando icono de archivador: {e}")

    if HAS_PIL and icon_png.exists() and (not icon_ico.exists() or icon_png.stat().st_mtime > icon_ico.stat().st_mtime):
        try:
            img = Image.open(icon_png)
            img_ico = img.resize((256, 256), Image.Resampling.LANCZOS)
            img_ico.save(icon_ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            logger.info(f"Icono ICO de archivador actualizado en {icon_ico.name}")
        except Exception as e:
            logger.error(f"Error convirtiendo archive_icon.png a ICO: {e}")

    return icon_png


if __name__ == "__main__":
    ensure_app_icon(Path("assets"))

