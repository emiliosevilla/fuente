import os
import sys
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Intenta importar psutil o implementa mediciones estándar con os / sys
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import json
    HAS_REQUESTS = False


class RAMGovernor:
    """Administra la memoria RAM del sistema y selecciona dinámicamente el modelo LLM adecuado."""

    def __init__(self, ollama_url: str = "http://localhost:11434", safety_margin_pct: float = 0.35):
        self.ollama_url = ollama_url.rstrip("/")
        self.safety_margin_pct = safety_margin_pct

    def get_system_ram_info(self) -> Dict[str, Any]:
        """Obtiene información precisa de RAM del sistema."""
        total_gb = 16.0
        available_gb = 8.0

        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024 ** 3)
            available_gb = mem.available / (1024 ** 3)
        else:
            # Fallback multiplataforma cuando psutil no está presente
            try:
                if sys.platform == "darwin":
                    import subprocess
                    out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
                    total_gb = int(out) / (1024 ** 3)
                    available_gb = total_gb * 0.5
                elif sys.platform.startswith("linux"):
                    with open("/proc/meminfo", "r") as f:
                        lines = f.readlines()
                    for l in lines:
                        if "MemTotal" in l:
                            total_gb = int(l.split()[1]) / (1024 ** 2)
                        elif "MemAvailable" in l:
                            available_gb = int(l.split()[1]) / (1024 ** 2)
            except Exception as e:
                logger.debug(f"Fallback RAM measurement error: {e}")

        return {
            "total_gb": round(total_gb, 2),
            "available_gb": round(available_gb, 2),
            "used_pct": round((1.0 - (available_gb / max(total_gb, 1.0))) * 100, 1),
            "safety_margin_gb": round(total_gb * self.safety_margin_pct, 2),
        }

    def recommend_model(self) -> str:
        """Selecciona el modelo óptimo garantizando la holgura de RAM para el sistema host."""
        ram_info = self.get_system_ram_info()
        available_gb = ram_info["available_gb"]
        total_gb = ram_info["total_gb"]

        logger.info(f"RAM Total: {total_gb} GB, RAM Disponible: {available_gb} GB")

        if available_gb <= 4.0 or total_gb <= 8.0:
            model = "qwen2.5:1.5b"
        elif available_gb <= 10.0 or total_gb <= 16.0:
            model = "qwen2.5:3b"
        elif available_gb <= 20.0 or total_gb <= 32.0:
            model = "qwen2.5:7b"
        elif available_gb <= 32.0:
            model = "qwen2.5:14b"
        else:
            model = "command-r:35b"

        logger.info(f"Modelo seleccionado por RAMGovernor: '{model}'")
        return model

    def check_ollama_status(self) -> bool:
        """Verifica si Ollama está en ejecución."""
        if HAS_REQUESTS:
            try:
                resp = requests.get(f"{self.ollama_url}/api/tags", timeout=3)
                return resp.status_code == 200
            except Exception:
                return False
        else:
            try:
                req = urllib.request.Request(f"{self.ollama_url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200
            except Exception:
                return False

    def ensure_model_available(self, model_name: str) -> bool:
        """Comprueba si el modelo está descargado en Ollama."""
        if not self.check_ollama_status():
            logger.warning(f"Ollama no está respondiendo en {self.ollama_url}")
            return False
        return True
