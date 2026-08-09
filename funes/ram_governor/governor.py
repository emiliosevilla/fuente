import json
import logging
import os
import sys
import time
import ctypes
import urllib.request
from typing import Any, Dict, List, Optional, Set, Union

from funes.ram_governor.budget import (
    MODEL_CATALOG,
    OLLAMA_PURGE_KEEP_ALIVE,
    BudgetDecision,
    MemorySnapshot,
    ResourceKind,
    evaluate_resource,
    get_model_metadata,
    list_resource_budgets,
    measured_snapshot,
    select_llm_model,
    should_fallback_to_bm25 as budget_should_fallback_to_bm25,
    unavailable_snapshot,
    viable_models,
)

logger = logging.getLogger(__name__)

OS_WHITELIST: Dict[str, Set[str]] = {
    "darwin": {
        "launchd", "kernel_task", "WindowServer", "Finder", "Dock",
        "systemmanagementd", "loginwindow", "ControlCenter", "coreaudiod", "syspolicyd"
    },
    "win32": {
        "System", "svchost.exe", "explorer.exe", "lsass.exe", "services.exe",
        "csrss.exe", "smss.exe", "winlogon.exe", "dwm.exe", "spoolsv.exe"
    },
    "linux": {
        "systemd", "kthreadd", "dbus-daemon", "Xorg", "gnome-shell", "init"
    }
}

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


try:
    import requests
    HAS_REQUESTS = True
except ImportError:
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
        self._last_budget_decision: Optional[BudgetDecision] = None
        self._last_ollama_state_error: Optional[str] = None

    def get_top_resource_hogs(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Obtiene la lista de los N procesos de usuario que más RAM consumen, excluyendo la whitelist del SO."""
        if not HAS_PSUTIL:
            return []

        current_platform = sys.platform if sys.platform in OS_WHITELIST else ("darwin" if sys.platform == "darwin" else "win32")
        whitelist = OS_WHITELIST.get(current_platform, OS_WHITELIST.get("darwin", set()))
        my_pid = os.getpid()

        hogs = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    pinfo = proc.info
                    pid = pinfo.get('pid')
                    name = pinfo.get('name') or ''
                    mem_info = pinfo.get('memory_info')

                    if not pid or pid == my_pid:
                        continue
                    if name.lower() in {w.lower() for w in whitelist}:
                        continue
                    if mem_info is None:
                        continue

                    mem_mb = round(mem_info.rss / (1024 * 1024), 2)
                    if mem_mb > 50.0:  # Filtrar procesos irrelevantes de menos de 50MB
                        hogs.append({
                            "pid": pid,
                            "name": name,
                            "memory_mb": mem_mb
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            logger.warning(f"Error al listar procesos acaparadores de RAM: {e}")

        hogs.sort(key=lambda x: x["memory_mb"], reverse=True)
        return hogs[:limit]

    def terminate_processes(self, pids: List[int]) -> Dict[str, List[int]]:
        """Termina de forma segura los PIDs especificados en 2 fases (SIGTERM ➔ espera 2s ➔ SIGKILL).
        Previene la terminación de procesos pertenecientes a la Whitelist del SO o al proceso propio.
        """
        results = {"terminated": [], "failed": [], "skipped_whitelisted": []}

        current_platform = sys.platform if sys.platform in OS_WHITELIST else ("darwin" if sys.platform == "darwin" else "win32")
        whitelist = OS_WHITELIST.get(current_platform, OS_WHITELIST.get("darwin", set()))
        my_pid = os.getpid()

        remaining_pids = []
        for pid in pids:
            if pid == my_pid:
                results["skipped_whitelisted"].append(pid)
            else:
                remaining_pids.append(pid)

        if not HAS_PSUTIL:
            results["failed"].extend(remaining_pids)
            return results

        procs_to_terminate = []
        for pid in remaining_pids:
            try:
                proc = psutil.Process(pid)
                pname = proc.name() or ""
                if pname.lower() in {w.lower() for w in whitelist}:
                    results["skipped_whitelisted"].append(pid)
                    continue
                procs_to_terminate.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                results["failed"].append(pid)

        # Fase 1: Suave (SIGTERM)
        for proc in procs_to_terminate:
            try:
                proc.terminate()
            except Exception as e:
                logger.debug(f"SIGTERM error para PID {proc.pid}: {e}")

        # Espera de 2 segundos para dar tiempo a guardar estado
        time.sleep(2)

        # Fase 2: Forzado (SIGKILL si persiste)
        for proc in procs_to_terminate:
            try:
                if proc.is_running():
                    proc.kill()
                results["terminated"].append(proc.pid)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                results["terminated"].append(proc.pid)
            except Exception as e:
                logger.warning(f"No se pudo forzar el cierre del PID {proc.pid}: {e}")
                results["failed"].append(proc.pid)

        return results

    def measure_memory(self) -> MemorySnapshot:
        """Measure host RAM. Never invent a precise available_gb when unmeasured."""
        if HAS_PSUTIL:
            try:
                mem = psutil.virtual_memory()
                return measured_snapshot(
                    total_gb=mem.total / (1024 ** 3),
                    available_gb=mem.available / (1024 ** 3),
                    safety_margin_pct=self.safety_margin_pct,
                )
            except Exception as exc:
                logger.debug("psutil virtual_memory failed: %s", exc)
                return unavailable_snapshot(
                    self.safety_margin_pct,
                    error=f"psutil_error: {exc}",
                )

        try:
            if sys.platform == "win32":
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    return measured_snapshot(
                        total_gb=stat.ullTotalPhys / (1024 ** 3),
                        available_gb=stat.ullAvailPhys / (1024 ** 3),
                        safety_margin_pct=self.safety_margin_pct,
                    )
                return unavailable_snapshot(
                    self.safety_margin_pct,
                    error="GlobalMemoryStatusEx_failed",
                )

            if sys.platform == "darwin":
                # hw.memsize yields total RAM only. Do not fabricate available_gb
                # as a fraction of total (previous bug).
                import subprocess

                out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
                total_gb = round(int(out) / (1024 ** 3), 2)
                return unavailable_snapshot(
                    self.safety_margin_pct,
                    error="macos_available_memory_requires_psutil",
                    total_gb=total_gb,
                )

            if sys.platform.startswith("linux"):
                total_kb = None
                available_kb = None
                with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.startswith("MemTotal:"):
                            total_kb = int(line.split()[1])
                        elif line.startswith("MemAvailable:"):
                            available_kb = int(line.split()[1])
                if total_kb is not None and available_kb is not None:
                    return measured_snapshot(
                        total_gb=total_kb / (1024 ** 2),
                        available_gb=available_kb / (1024 ** 2),
                        safety_margin_pct=self.safety_margin_pct,
                    )
                return unavailable_snapshot(
                    self.safety_margin_pct,
                    error="linux_meminfo_incomplete",
                    total_gb=round(total_kb / (1024 ** 2), 2) if total_kb else None,
                )
        except Exception as exc:
            logger.debug("Fallback RAM measurement error: %s", exc)
            return unavailable_snapshot(
                self.safety_margin_pct,
                error=f"measurement_error: {exc}",
            )

        return unavailable_snapshot(
            self.safety_margin_pct,
            error=f"unsupported_platform:{sys.platform}",
        )

    def should_fallback_to_bm25(self) -> bool:
        """Determina si se debe aplicar la degradación transparente a búsqueda léxica BM25."""
        return budget_should_fallback_to_bm25(self.measure_memory())

    def get_system_ram_info(self) -> Dict[str, Any]:
        """Obtiene información de RAM. ``available_gb`` is None when not measured."""
        snapshot = self.measure_memory()
        return snapshot.to_dict()

    def recommend_model_decision(self) -> BudgetDecision:
        """Select an LLM and return the full budget decision + reason."""
        decision = select_llm_model(self.measure_memory())
        self._last_budget_decision = decision
        logger.info(
            "Modelo seleccionado por RAMGovernor: '%s' (%s)",
            decision.model_id,
            decision.reason,
        )
        return decision

    def recommend_model(self) -> str:
        """Selecciona el modelo óptimo garantizando la holgura de RAM para el sistema host."""
        decision = self.recommend_model_decision()
        return decision.model_id or MODEL_CATALOG[0].id

    def last_budget_decision(self) -> Optional[Dict[str, Any]]:
        if self._last_budget_decision is None:
            return None
        return self._last_budget_decision.to_dict()

    def evaluate_resource_budget(
        self,
        kind: Union[str, ResourceKind],
        *,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate whether a named resource class fits the current snapshot."""
        resource_kind = kind if isinstance(kind, ResourceKind) else ResourceKind(kind)
        decision = evaluate_resource(
            resource_kind,
            self.measure_memory(),
            model_id=model_id,
        )
        return decision.to_dict()

    def get_resource_budgets(self) -> List[Dict[str, Any]]:
        return list_resource_budgets()

    def get_model_catalog(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in MODEL_CATALOG]

    def get_viable_models(self) -> list[Dict[str, Any]]:
        """Devuelve la lista de modelos de IA viables según la memoria RAM física.
        Filtra y oculta automáticamente cualquier modelo que exceda la capacidad o margen de seguridad.
        """
        return viable_models(self.measure_memory())

    def _http_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        url = f"{self.ollama_url}{path}"
        if HAS_REQUESTS:
            if method.upper() == "GET":
                resp = requests.get(url, timeout=timeout)
            else:
                resp = requests.post(url, json=payload or {}, timeout=timeout)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} from {path}")
            if not resp.content:
                return {}
            return resp.json()

        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))

    def check_ollama_status(self) -> bool:
        """Verifica si Ollama está en ejecución."""
        try:
            self._http_json("GET", "/api/tags", timeout=3)
            return True
        except Exception:
            return False

    def get_ollama_process_state(self) -> Dict[str, Any]:
        """Query Ollama loaded-model state via ``/api/ps``. Failures are recorded, not raised."""
        try:
            data = self._http_json("GET", "/api/ps", timeout=3)
            models = data.get("models") or []
            self._last_ollama_state_error = None
            return {
                "ok": True,
                "supported": True,
                "models": models,
                "error": None,
            }
        except Exception as exc:
            message = f"ollama_ps_failed: {exc}"
            self._last_ollama_state_error = message
            logger.debug("Ollama process/model state query failed: %s", exc)
            return {
                "ok": False,
                "supported": True,
                "models": [],
                "error": message,
            }

    def purge_model(self, model_name: str) -> Dict[str, Any]:
        """Unload a model using documented ``keep_alive=0`` (policy purge, not force-kill)."""
        meta = get_model_metadata(model_name)
        try:
            # Official unload: empty prompt + keep_alive=0 → done_reason unload.
            result = self._http_json(
                "POST",
                "/api/generate",
                payload={
                    "model": model_name,
                    "prompt": "",
                    "keep_alive": OLLAMA_PURGE_KEEP_ALIVE,
                    "stream": False,
                },
                timeout=30,
            )
            return {
                "ok": True,
                "model": model_name,
                "policy": "keep_alive=0",
                "force_kill": False,
                "done_reason": result.get("done_reason"),
                "estimated_ram_gb": meta.estimated_ram_gb if meta else None,
                "error": None,
            }
        except Exception as exc:
            message = f"purge_failed: {exc}"
            logger.warning(
                "Ollama purge via keep_alive=%s failed for %s: %s",
                OLLAMA_PURGE_KEEP_ALIVE,
                model_name,
                exc,
            )
            return {
                "ok": False,
                "model": model_name,
                "policy": "keep_alive=0",
                "force_kill": False,
                "done_reason": None,
                "estimated_ram_gb": meta.estimated_ram_gb if meta else None,
                "error": message,
            }

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
        status = ram_info.get("measurement_status")
        print(f"[+] Measurement status: {status}")
        print(f"[+] RAM Total detectada: {ram_info['total_gb']} GB")
        if ram_info.get("available_gb") is None:
            print("[+] RAM Libre/Disponible: measurement_unavailable (no precise figure)")
        else:
            print(f"[+] RAM Libre/Disponible: {ram_info['available_gb']} GB")
        print(f"[+] Margen de seguridad: {int(self.safety_margin_pct * 100)}% reservado para evitar lag en el sistema host.")

        decision = self.recommend_model_decision()
        model = decision.model_id or MODEL_CATALOG[0].id
        print(f"[+] Modelo Qwen óptimo seleccionado: '{model}'")
        print(f"[+] Motivo: {decision.reason}")

        if not self.check_ollama_status():
            print("[!] Ollama no está respondiendo en http://localhost:11434. Asegúrate de iniciarlo.")
            return model

        already_installed = False
        try:
            tags = self._http_json("GET", "/api/tags", timeout=5)
            models = [m.get("name") for m in tags.get("models", [])]
            if any(model in (m or "") for m in models):
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
