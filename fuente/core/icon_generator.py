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

    return icon_png


if __name__ == "__main__":
    ensure_app_icon(Path("assets"))
