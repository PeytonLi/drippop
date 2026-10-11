from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider_mode: Literal["fake", "live"] = "fake"
    database_url: str = "postgresql://127.0.0.1:5432/postgres"
    supabase_url: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_secret_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str | None = None
    youcam_api_key: str = ""
    storage_backend: Literal["supabase", "local"] | None = None
    local_storage_dir: Path = _BACKEND_DIR / ".local-storage"
    storage_bucket: str = "drippop-private"
    contracts_dir: Path = _REPO_ROOT / "contracts"
    daily_paid_attempt_cap: int = 0
    detect_daily_cap_per_uid: int = 200
    detect_daily_cap_project: int = 2000
    max_image_bytes: int = 8_388_608
    max_image_side: int = 4096
    max_image_pixels: int = 16_777_216
    min_gen_short_side: int = 384
    min_gen_long_side: int = 512
    poll_after_ms: int = 3000
    image_ttl_s: int = 86400
    record_ttl_s: int = 2_592_000
    job_deadline_s: int = 900
    lease_s: int = 120
    handler_timeout_s: int = 60
    dispatch_max_attempts: int = 5
    max_checks: int = 120
    check_interval_s: int = 3
    detect_timeout_s: int = 20
    max_result_bytes: int = 15_000_000
    reconcile_interval_s: int = 300
    worker_idle_sleep_s: float = 1.0

    @model_validator(mode="after")
    def _derive(self) -> "Settings":
        if self.handler_timeout_s >= self.lease_s:
            raise ValueError("HANDLER_TIMEOUT_S must be < LEASE_S")
        if self.supabase_url:
            if not self.supabase_jwks_url:
                self.supabase_jwks_url = f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
            if not self.supabase_jwt_issuer:
                self.supabase_jwt_issuer = f"{self.supabase_url}/auth/v1"
        if self.storage_backend is None:
            if self.provider_mode == "fake" and not self.supabase_secret_key:
                self.storage_backend = "local"
            else:
                self.storage_backend = "supabase"
        return self
