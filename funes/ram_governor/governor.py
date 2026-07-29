import os
import sys
import ctypes
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

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


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class RAMGovernor:
    """Administra la memoria RAM del sistema y selecciona dinámicamente el modelo LLM adecuado."""

    def __init__(self, ollama_url: str = "http://localhost:11434", safety_margin_pct: float = 0.35):
        self.ollama_url = ollama_url.rstrip("/")
        self.safety_margin_pct = safety_margin_pct

    def get_system_ram_info(self) -> Dict[str, Any]:
        """Obtiene información precisa de RAM del sistema (compatible con macOS, Windows y Linux)."""
        total_gb = 16.0
        available_gb = 8.0

        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024 ** 3)
            available_gb = mem.available / (1024 ** 3)
        else:
            try:
                if sys.platform == "win32":
                    stat = MEMORYSTATUSEX()
                    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                        total_gb = stat.ullTotalPhys / (1024 ** 3)
                        available_gb = stat.ullAvailPhys / (1024 ** 3)
                elif sys.platform == "darwin":
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

        if total_gb <= 8.0 or available_gb <= 3.5:
            model = "qwen2.5:1.5b"
            logger.info("⚡ [MODO ECO 8GB] Equipo con 8 GB RAM o baja memoria libre. Usando modelo ultraligero con descarga inmediata.")
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
        """Comprueba si el modelo está descargado en Ollama. Si no, solicita el pull."""
        if not self.check_ollama_status():
            logger.warning(f"Ollama no está respondiendo en {self.ollama_url}")
            return False

        try:
            if HAS_REQUESTS:
                resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = [m.get("name") for m in resp.json().get("models", [])]
                    if any(model_name in m for m in models):
                        return True

                logger.info(f"Descargando modelo '{model_name}' en Ollama...")
                pull_resp = requests.post(
                    f"{self.ollama_url}/api/pull",
                    json={"name": model_name, "stream": False},
                    timeout=600,
                )
                return pull_resp.status_code == 200
            else:
                req = urllib.request.Request(f"{self.ollama_url}/api/tags")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name") for m in data.get("models", [])]
                    if any(model_name in m for m in models):
                        return True
                return True
        except Exception as e:
            logger.error(f"Error comprobando disponibilidad del modelo '{model_name}': {e}")
            return False

    def setup_optimal_model(self) -> str:
        """Detecta la RAM del sistema, selecciona el modelo Qwen óptimo manteniendo la holgura del 35% y asegura su descarga."""
        ram_info = self.get_system_ram_info()
        print("\n=======================================================")
        print("    CONFIGURACION DE MODELO IA SEGÚN RAM DISPONIBLE")
        print("=======================================================")
        print(f"[+] RAM Total detectada: {ram_info['total_gb']} GB")
        print(f"[+] RAM Libre/Disponible: {ram_info['available_gb']} GB")
        print(f"[+] Margen de seguridad: 35% reservado para evitar lag en el sistema host.")

        model = self.recommend_model()
        print(f"[+] Modelo Qwen óptimo seleccionado: '{model}'")

        if not self.check_ollama_status():
            print("[!] Ollama no está respondiendo en http://localhost:11434. Asegúrate de iniciarlo.")
            return model

        already_installed = False
        try:
            if HAS_REQUESTS:
                resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = [m.get("name") for m in resp.json().get("models", [])]
                    if any(model in m for m in models):
                        already_installed = True
        except Exception:
            pass

        if already_installed:
            print(f"[+] El modelo '{model}' ya está instalado y listo en Ollama.")
            return model

        print(f"[*] Descargando modelo '{model}' en Ollama (esto puede tardar unos minutos)...")
        import shutil
        import subprocess
        ollama_bin = shutil.which("ollama")
        if ollama_bin:
            try:
                res = subprocess.run([ollama_bin, "pull", model])
                if res.returncode == 0:
                    print(f"[+] Modelo '{model}' instalado exitosamente.")
                    return model
            except Exception as e:
                logger.debug(f"CLI pull error: {e}")

        if self.ensure_model_available(model):
            print(f"[+] Modelo '{model}' descargado e instalado correctamente.")
        else:
            print(f"[!] No se pudo descargar automáticamente '{model}'. Puedes descargarlo con 'ollama pull {model}'.")

        return model


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gov = RAMGovernor()
    gov.setup_optimal_model()

