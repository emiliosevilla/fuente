"""Safe, release-backed update checks for the local Gestajo companion."""
from __future__ import annotations

import json
import platform as platform_module
import re
import webbrowser
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RELEASE_URL = "https://api.github.com/repos/emiliosevilla/fuente/releases/latest"
ASSET_BY_PLATFORM = {
    "Darwin": "Fuente_Distribucion_macOS.dmg",
    "Windows": "Fuente_Distribucion_Windows.zip",
}
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclass(frozen=True)
class AgentUpdate:
    state: str
    current_version: str
    available_version: str | None
    download_url: str | None

    def public(self) -> dict[str, object]:
        return {
            "state": self.state,
            "current_version": self.current_version,
            "available_version": self.available_version,
        }


def _version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    parts = [int(part) for part in match.groups() if part is not None]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _latest_release() -> Mapping[str, object] | None:
    request = Request(RELEASE_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Fuente-Gestajo-Agent"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


class AgentUpdater:
    """Checks only the fixed Fuente release endpoint and opens a native asset."""

    def __init__(
        self,
        release_reader: Callable[[], Mapping[str, object] | None] = _latest_release,
        opener: Callable[[str, int], bool] = webbrowser.open,
    ) -> None:
        self._release_reader = release_reader
        self._opener = opener

    def inspect(self, current_version: str, *, active_jobs: int, platform_name: str | None = None) -> AgentUpdate:
        if active_jobs > 0:
            return AgentUpdate("waiting_for_caudal", current_version, None, None)
        release = self._release_reader()
        if release is None:
            return AgentUpdate("unavailable", current_version, None, None)
        tag = release.get("tag_name")
        latest = tag if isinstance(tag, str) and _version(tag) is not None else None
        current = _version(current_version)
        if latest is None or current is None:
            return AgentUpdate("unavailable", current_version, None, None)
        if _version(latest) <= current:
            return AgentUpdate("current", current_version, latest.removeprefix("v"), None)
        asset_name = ASSET_BY_PLATFORM.get(platform_name or platform_module.system())
        assets = release.get("assets")
        if asset_name is None or not isinstance(assets, list):
            return AgentUpdate("unavailable", current_version, latest.removeprefix("v"), None)
        url = next((asset.get("browser_download_url") for asset in assets if isinstance(asset, Mapping) and asset.get("name") == asset_name), None)
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            return AgentUpdate("unavailable", current_version, latest.removeprefix("v"), None)
        return AgentUpdate("available", current_version, latest.removeprefix("v"), url)

    def launch(self, update: AgentUpdate) -> AgentUpdate:
        if update.state != "available" or update.download_url is None:
            return update
        if not self._opener(update.download_url, 2):
            return AgentUpdate("unavailable", update.current_version, update.available_version, None)
        return AgentUpdate("download_started", update.current_version, update.available_version, None)
