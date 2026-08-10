"""Read-only first-run health probes for the Funes local runtime."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from funes.config import AppConfig, is_loopback_ollama_url
from funes.core.anythingllm_config import get_anythingllm_paths
from funes.domain.runtime_policy import resolve_runtime_policy
from funes.ram_governor.budget import BudgetDecision


HealthStatus = Literal[
    "ok",
    "missing",
    "unreachable",
    "blocked",
    "optional",
    "unknown",
]


@dataclass(frozen=True)
class HealthItem:
    status: HealthStatus
    label: str
    detail: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "label": self.label,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass(frozen=True)
class HealthSnapshot:
    checked_at: str
    vault: HealthItem
    ollama: HealthItem
    installed_models: tuple[str, ...]
    loaded_models: tuple[str, ...]
    tools: Mapping[str, HealthItem]
    extras: Mapping[str, HealthItem]
    policy: Mapping[str, object]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "vault": self.vault.to_dict(),
            "ollama": self.ollama.to_dict(),
            "installed_models": list(self.installed_models),
            "loaded_models": list(self.loaded_models),
            "tools": {
                name: item.to_dict() for name, item in self.tools.items()
            },
            "extras": {
                name: item.to_dict() for name, item in self.extras.items()
            },
            "policy": dict(self.policy),
        }


HttpJsonProbe = Callable[[str, float], Mapping[str, Any]]
WhichProbe = Callable[[str], str | None]
FindSpecProbe = Callable[[str], object | None]
PathProbe = Callable[[Path], bool]
AccessProbe = Callable[[str | os.PathLike[str], int], bool]
BudgetResolver = Callable[[], BudgetDecision | None]


class _RedirectRejectedError(OSError):
    """Raised when a health probe receives any HTTP redirect."""


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        location = headers.get("Location") or newurl or "unknown"
        raise _RedirectRejectedError(f"HTTP redirect rejected: {location}")


def _http_json(url: str, timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirectHandler(),
    )
    with opener.open(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("health endpoint did not return an object")
    return payload


class HealthService:
    """Measure current local health without changing the machine or the vault."""

    OLLAMA_TIMEOUT_SECONDS = 1.0
    _OPTIONAL_EXTRAS: Mapping[str, tuple[str, ...]] = {
        "audio": ("faster_whisper",),
        "ocr": ("pytesseract", "PIL"),
        "office": ("markitdown", "docling"),
        "webview": ("webview",),
    }

    def __init__(
        self,
        config: AppConfig,
        *,
        http_json: HttpJsonProbe | None = None,
        which: WhichProbe | None = None,
        find_spec: FindSpecProbe | None = None,
        path_exists: PathProbe | None = None,
        path_is_dir: PathProbe | None = None,
        access: AccessProbe | None = None,
        budget_resolver: BudgetResolver | None = None,
        budget: BudgetDecision | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._http_json = http_json or _http_json
        self._which = which or shutil.which
        self._find_spec = find_spec or importlib.util.find_spec
        self._path_exists = path_exists or Path.exists
        self._path_is_dir = path_is_dir or Path.is_dir
        self._access = access or os.access
        self._budget_resolver = budget_resolver
        self._budget = budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def snapshot(self) -> HealthSnapshot:
        installed_models, loaded_models, ollama = self._probe_ollama()
        return HealthSnapshot(
            checked_at=self._clock().isoformat(),
            vault=self._probe_vault(),
            ollama=ollama,
            installed_models=installed_models,
            loaded_models=loaded_models,
            tools={
                "tesseract": self._probe_tool(
                    "tesseract", "Tesseract", required=False
                ),
                "ffmpeg": self._probe_tool(
                    "ffmpeg", "FFmpeg", required=False
                ),
                "anythingllm": self._probe_anythingllm(),
            },
            extras=self._probe_extras(),
            policy=self._probe_policy(installed_models),
        )

    def _probe_vault(self) -> HealthItem:
        path = Path(self.config.vault.vault_path)
        try:
            if not self._path_exists(path):
                return HealthItem(
                    status="missing",
                    label="Vault",
                    detail="El Vault no existe.",
                    required=True,
                )
            if not self._path_is_dir(path):
                return HealthItem(
                    status="missing",
                    label="Vault",
                    detail="La ruta del Vault no es un directorio.",
                    required=True,
                )
            if not self._access(path, os.W_OK):
                return HealthItem(
                    status="blocked",
                    label="Vault",
                    detail="El sistema no reporta permiso de escritura.",
                    required=True,
                )
            return HealthItem(
                status="ok",
                label="Vault",
                detail=(
                    "Directorio disponible; permiso de escritura reportado por el SO "
                    "(no es una escritura de prueba)."
                ),
                required=True,
            )
        except OSError as error:
            return HealthItem(
                status="unknown",
                label="Vault",
                detail=f"No se pudo consultar el Vault: {error}",
                required=True,
            )

    def _probe_ollama(self) -> tuple[tuple[str, ...], tuple[str, ...], HealthItem]:
        url = str(self.config.ollama_url).rstrip("/")
        if not is_loopback_ollama_url(url):
            return (
                (),
                (),
                HealthItem(
                    status="blocked",
                    label="Ollama",
                    detail="El endpoint no es loopback; la comprobación está bloqueada.",
                    required=True,
                ),
            )

        try:
            tags = self._http_json(
                f"{url}/api/tags", self.OLLAMA_TIMEOUT_SECONDS
            )
            installed = self._model_names(tags)
        except (TimeoutError, OSError) as error:
            return (
                (),
                (),
                HealthItem(
                    status="unreachable",
                    label="Ollama",
                    detail=f"Ollama loopback no responde dentro de 1 s: {error}",
                    required=True,
                ),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return (
                (),
                (),
                HealthItem(
                    status="unknown",
                    label="Ollama",
                    detail=f"Respuesta de Ollama no válida: {error}",
                    required=True,
                ),
            )
        except Exception as error:
            return (
                (),
                (),
                HealthItem(
                    status="unreachable",
                    label="Ollama",
                    detail=f"No se pudo consultar Ollama en loopback: {error}",
                    required=True,
                ),
            )

        try:
            running = self._http_json(
                f"{url}/api/ps", self.OLLAMA_TIMEOUT_SECONDS
            )
            loaded = self._model_names(running)
        except (TimeoutError, OSError) as error:
            return (
                installed,
                (),
                HealthItem(
                    status="unreachable",
                    label="Ollama",
                    detail=(
                        "Modelos instalados medidos mediante /api/tags; "
                        f"falló la medición de modelos cargados mediante /api/ps "
                        f"dentro de 1 s: {error}"
                    ),
                    required=True,
                ),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return (
                installed,
                (),
                HealthItem(
                    status="unknown",
                    label="Ollama",
                    detail=(
                        "Modelos instalados medidos mediante /api/tags; "
                        "falló la medición de modelos cargados mediante /api/ps: "
                        f"{error}"
                    ),
                    required=True,
                ),
            )
        except Exception as error:
            return (
                installed,
                (),
                HealthItem(
                    status="unreachable",
                    label="Ollama",
                    detail=(
                        "Modelos instalados medidos mediante /api/tags; "
                        "falló la medición de modelos cargados mediante /api/ps: "
                        f"{error}"
                    ),
                    required=True,
                ),
            )

        return (
            installed,
            loaded,
            HealthItem(
                status="ok",
                label="Ollama",
                detail="Endpoint loopback accesible; se han consultado /api/tags y /api/ps.",
                required=True,
            ),
        )

    @staticmethod
    def _model_names(payload: Mapping[str, Any]) -> tuple[str, ...]:
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raise ValueError("models must be a list")
        names: list[str] = []
        for model in raw_models:
            if not isinstance(model, Mapping):
                raise ValueError("each model must be an object")
            name = model.get("name")
            if isinstance(name, str) and name not in names:
                names.append(name)
        return tuple(names)

    def _probe_tool(self, command: str, label: str, *, required: bool) -> HealthItem:
        try:
            location = self._which(command)
        except Exception as error:
            return HealthItem(
                status="unknown",
                label=label,
                detail=f"No se pudo consultar {label}: {error}",
                required=required,
            )
        if location:
            return HealthItem(
                status="ok",
                label=label,
                detail=f"Ejecutable encontrado en {location}.",
                required=required,
            )
        return HealthItem(
            status="optional" if not required else "missing",
            label=label,
            detail=f"{label} no está instalado; la capacidad es opcional.",
            required=required,
        )

    def _probe_anythingllm(self) -> HealthItem:
        try:
            app_path = get_anythingllm_paths().get("app_path")
            if app_path is not None and self._path_exists(app_path):
                return HealthItem(
                    status="ok",
                    label="AnythingLLM",
                    detail=f"Aplicación encontrada en {app_path}.",
                    required=False,
                )
        except OSError:
            pass
        return self._probe_tool("anythingllm", "AnythingLLM", required=False)

    def _probe_extras(self) -> dict[str, HealthItem]:
        extras: dict[str, HealthItem] = {}
        for extra, modules in self._OPTIONAL_EXTRAS.items():
            missing: list[str] = []
            for module in modules:
                try:
                    available = self._find_spec(module) is not None
                except (ImportError, ModuleNotFoundError, ValueError):
                    available = False
                if not available:
                    missing.append(module)
            if missing:
                extras[extra] = HealthItem(
                    status="optional",
                    label=f"Extra Python {extra}",
                    detail=f"No disponible: {', '.join(missing)}.",
                    required=False,
                )
            else:
                extras[extra] = HealthItem(
                    status="ok",
                    label=f"Extra Python {extra}",
                    detail="Dependencias Python disponibles.",
                    required=False,
                )
        return extras

    def _probe_policy(self, installed_models: tuple[str, ...]) -> Mapping[str, object]:
        budget = self._budget
        if budget is None and self._budget_resolver is not None:
            try:
                budget = self._budget_resolver()
            except Exception as error:
                return {
                    "status": "unknown",
                    "detail": f"No se pudo medir la política efectiva: {error}",
                }
        try:
            policy = resolve_runtime_policy(
                self.config,
                budget,
                installed_models=installed_models,
            )
        except Exception as error:
            return {
                "status": "unknown",
                "detail": f"No se pudo resolver la política efectiva: {error}",
            }
        return {
            "status": "ok",
            "profile": policy.profile.value,
            "retrieval_mode": policy.retrieval_mode,
            "vector_index_enabled": policy.vector_index_enabled,
            "audio_mode": policy.audio_mode.value,
            "whisper_model_path": (
                str(policy.whisper_model_path)
                if policy.whisper_model_path is not None
                else None
            ),
            "allow_model_download": policy.allow_model_download,
            "selected_model": policy.selected_model,
            "llm_available": policy.llm_available,
            "reason": policy.reason,
        }
