"""Check the exact interpreter used by the launcher; never install globally."""
import sys


def require_cover_dependencies():
    try:
        import PIL
        from PIL import Image
        major = int(PIL.__version__.split(".")[0])
        if major < 10:
            raise ImportError("Pillow 10 or later is required")
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            f"Pillow>=10 is required in this Python environment ({sys.executable}). "
            "Create/activate an isolated venv, then use its Python to run "
            "-m pip install -r requirements.txt and every installer/runtime command."
        ) from exc
    return {"python": sys.executable, "Pillow": PIL.__version__}
