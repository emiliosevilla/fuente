import json
import logging
import os
import sys
import time
import ctypes
import urllib.request
from typing import Any, Dict, List, Optional, Set, Union

from fuente.ram_governor.budget import (
    BM25_ONLY_POLICY,
    MODEL_CATALOG,
    OLLAMA_PURGE_KEEP_ALIVE,
    BudgetDecision,
    MemorySnapshot,
    ResourceKind,
    evaluate_resource,
    get_model_metadata,
    list_resource_budgets,
    llm_inference_mode,
    measured_snapshot,
    select_llm_model,
    select_optimal_model,
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
        decision = select_optimal_model(self.measure_memory())
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
        if not decision.allowed or llm_inference_mode(decision) == BM25_ONLY_POLICY:
            return ""
        return decision.model_id or ""

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

    def get_installed_model_names(self) -> tuple[str, ...]:
        """Return exact model names installed in Ollama, without loading or pulling."""
        data = self._http_json("GET", "/api/tags", timeout=3)
        names = {
            str(item.get("name")).strip()
            for item in (data.get("models") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        return tuple(sorted(names))

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

    def ensure_model_available(
        self, model_name: str, *, authorize_download: bool = False
    ) -> bool:
        """Check an exact installed model and pull only after explicit authorization."""
        if not self.check_ollama_status():
            logger.warning(f"Ollama no está respondiendo en {self.ollama_url}")
            return False

        try:
            if model_name in self.get_installed_model_names():
                return True
            if not authorize_download:
                logger.info(
                    "Model %s is not installed; download requires explicit authorization",
                    model_name,
                )
                return False

            if HAS_REQUESTS:
                pull_resp = requests.post(
                    f"{self.ollama_url}/api/pull",
                    json={"name": model_name, "stream": False},
                    timeout=600,
                )
                return pull_resp.status_code == 200

            req = urllib.request.Request(
                f"{self.ollama_url}/api/pull",
                data=json.dumps({"name": model_name, "stream": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Error comprobando disponibilidad del modelo '{model_name}': {e}")
            return False

    def check_cycle_model(
        self,
        model_name: Optional[str] = None,
        *,
        authorize_model_load: bool = False,
    ) -> Dict[str, Any]:
        """Re-measure RAM before an ETL LLM stage and return a user-action contract.

        The selected model comes from the setup/configuration. Installed-model
        state is used only to verify availability; it never selects a model.
        """
        snapshot = self.measure_memory()
        target = (model_name or "").strip() or None
        if target is None:
            setup_decision = select_optimal_model(snapshot)
            target = setup_decision.model_id

        if not snapshot.is_measured:
            instruction = (
                "No se pudo medir la RAM disponible con precisión. El ciclo queda "
                "en espera; cierra aplicaciones y vuelve a reanudar cuando la medición "
                "esté disponible. No se descargará ningún modelo automáticamente."
            )
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": None,
                "installed_models": [],
                "requires_user_confirmation": False,
                "authorization_used": False,
                "instruction": instruction,
                "reason": f"measurement_unavailable; {instruction}",
                "snapshot": snapshot.to_dict(),
            }

        try:
            installed = self.get_installed_model_names()
        except Exception as exc:
            instruction = (
                "No se pudo comprobar el modelo local. Inicia Ollama y vuelve a "
                "reanudar el ciclo; no se descargará ningún modelo automáticamente."
            )
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": None,
                "installed_models": [],
                "requires_user_confirmation": False,
                "authorization_used": False,
                "instruction": instruction,
                "reason": f"llm_model_inventory_unavailable: {exc}; {instruction}",
                "snapshot": snapshot.to_dict(),
            }

        target_fit = (
            evaluate_resource(ResourceKind.LLM_INFERENCE, snapshot, model_id=target)
            if target
            else None
        )
        compatible = select_optimal_model(snapshot)
        compatible_model = compatible.model_id if compatible.allowed else None
        target_is_installed = bool(target and target in installed)
        if target_is_installed and target_fit is not None and target_fit.allowed:
            return {
                "allowed": True,
                "model_id": target,
                "compatible_model": target,
                "installed_models": list(installed),
                "requires_user_confirmation": False,
                "authorization_used": False,
                "instruction": "",
                "reason": target_fit.reason,
                "snapshot": snapshot.to_dict(),
            }

        if compatible_model is None:
            instruction = (
                "La RAM disponible no permite ningún modelo compatible. Cierra "
                "aplicaciones y vuelve a reanudar el ciclo; Fuente permanecerá en espera."
            )
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": None,
                "installed_models": list(installed),
                "requires_user_confirmation": False,
                "authorization_used": False,
                "instruction": instruction,
                "reason": f"no_compatible_model; {instruction}",
                "snapshot": snapshot.to_dict(),
            }

        instruction = (
            "La RAM disponible no encaja con el modelo configurado. Cierra "
            "aplicaciones y vuelve a reanudar, o confirma cargar el mayor modelo "
            f"compatible ({compatible_model}). Fuente no cerrará procesos ni "
            "descargará modelos sin esa confirmación."
        )
        if not authorize_model_load:
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": compatible_model,
                "installed_models": list(installed),
                "requires_user_confirmation": True,
                "authorization_used": False,
                "instruction": instruction,
                "reason": f"llm_waiting_for_memory_or_authorization; {instruction}",
                "snapshot": snapshot.to_dict(),
            }

        if compatible_model not in installed and not self.ensure_model_available(
            compatible_model, authorize_download=True
        ):
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": compatible_model,
                "installed_models": list(installed),
                "requires_user_confirmation": False,
                "authorization_used": True,
                "instruction": (
                    f"No se pudo cargar {compatible_model}. Instálalo manualmente "
                    "y vuelve a reanudar el ciclo."
                ),
                "reason": f"authorized_model_load_failed; {instruction}",
                "snapshot": snapshot.to_dict(),
            }

        installed_after_load = tuple(
            sorted(set(installed) | {compatible_model})
        )
        final_snapshot = self.measure_memory()
        final_fit = evaluate_resource(
            ResourceKind.LLM_INFERENCE, final_snapshot, model_id=compatible_model
        )
        if not final_fit.allowed:
            return {
                "allowed": False,
                "model_id": target,
                "compatible_model": compatible_model,
                "installed_models": list(installed_after_load),
                "requires_user_confirmation": False,
                "authorization_used": True,
                "instruction": (
                    "La RAM sigue siendo insuficiente después de la confirmación. "
                    "Cierra aplicaciones y vuelve a reanudar; el ciclo queda en espera."
                ),
                "reason": f"authorized_model_still_does_not_fit; {final_fit.reason}",
                "snapshot": final_snapshot.to_dict(),
            }
        return {
            "allowed": True,
            "model_id": compatible_model,
            "compatible_model": compatible_model,
            "installed_models": list(installed_after_load),
            "requires_user_confirmation": False,
            "authorization_used": True,
            "instruction": "",
            "reason": final_fit.reason,
            "snapshot": final_snapshot.to_dict(),
        }

    def setup_optimal_model(self) -> str:
        """Select the setup model from installed RAM without downloading it."""
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
        if not decision.allowed or llm_inference_mode(decision) == BM25_ONLY_POLICY:
            print("[!] Modo BM25-only: no se instalará ningún modelo Ollama.")
            print(f"[+] Motivo: {decision.reason}")
            return ""

        model = decision.model_id
        if not model:
            print("[!] No hay un modelo LLM permitido; se mantiene el modo BM25-only.")
            print(f"[+] Motivo: {decision.reason}")
            return ""

        print(f"[+] Modelo Qwen óptimo seleccionado: '{model}'")
        print(f"[+] Motivo: {decision.reason}")

        if not self.check_ollama_status():
            print("[!] Ollama no está respondiendo en http://localhost:11434. Asegúrate de iniciarlo.")
            return model

        try:
            installed = self.get_installed_model_names()
        except Exception as exc:
            print(f"[!] No se pudo comprobar Ollama: {exc}")
            return model
        if model in installed:
            print(f"[+] El modelo '{model}' ya está instalado y listo en Ollama.")
        else:
            print(
                f"[!] El modelo '{model}' no está instalado. La instalación queda "
                "a la espera de una confirmación explícita del usuario."
            )

        return model


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gov = RAMGovernor()
    gov.setup_optimal_model()
