"""
配置加载 — config/config.yaml + .env, 分层覆盖:
  默认值 < config.yaml < 环境变量 < .env

复制即用:
  cp config/config.example.yaml config/config.yaml
  cp .env.example .env   # 填密钥
"""
import os
from pathlib import Path

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

_BASE = Path(__file__).resolve().parent.parent.parent  # meme-trader/


def _load_yaml(path: Path) -> dict:
    if not _HAS_YAML or not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Config:
    def __init__(self, config_path: str | None = None):
        _load_dotenv(_BASE / ".env")
        cfg_path = Path(config_path) if config_path else _BASE / "config" / "config.yaml"
        self._y = _load_yaml(cfg_path)
        self._env = os.environ

    def get(self, *keys, default=None):
        """config.get('chains','bsc','rpc') ; 环境变量优先"""
        env_key = "_".join(k.upper() for k in keys)
        if env_key in self._env:
            return self._env[env_key]
        cur = self._y
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # ---- 快捷访问 ----
    @property
    def chain(self) -> str:
        return self.get("chain", default="bsc")

    @property
    def dry_run(self) -> bool:
        v = self.get("dry_run", default=True)
        return str(v).lower() not in ("0", "false", "no")

    def gmgn_api_key(self) -> str | None:
        return self._env.get("GMGN_API_KEY")

    def j7_session(self) -> str | None:
        return self._env.get("J7_SESSION_ID")
