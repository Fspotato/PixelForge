"""模組註冊中心。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModuleConfig:
    """描述單一模組的註冊資訊。"""

    key: str
    label: str
    url_prefix: str = ""
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ModuleRegistry:
    """集中管理模組註冊資訊。"""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleConfig] = {}

    def register(self, config: ModuleConfig) -> ModuleConfig:
        if config.key in self._modules:
            raise ValueError(f"模組 {config.key} 已經註冊")
        self._modules[config.key] = config
        return config

    def unregister(self, key: str) -> ModuleConfig | None:
        return self._modules.pop(key, None)

    def get(self, key: str) -> ModuleConfig:
        try:
            return self._modules[key]
        except KeyError as exc:
            raise KeyError(f"找不到模組 {key}") from exc

    def is_registered(self, key: str) -> bool:
        return key in self._modules

    def list_modules(self, *, enabled_only: bool = False) -> list[ModuleConfig]:
        modules = list(self._modules.values())
        if enabled_only:
            return [module for module in modules if module.enabled]
        return modules

    def clear(self) -> None:
        self._modules.clear()
