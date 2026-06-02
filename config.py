"""Env loading (infra layer). Engine modules accept a config object/dict
rather than reading globals — spec §2."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Anchor to project root so callers from any cwd see the same env.
load_dotenv(Path(__file__).parent / ".env")


def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


@dataclass
class Config:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str
    customer_id: str
    chunk_size: int = 1000
    cache_freshness_days: int = 30
    historical_window_months: int = 6
    store_monthly_volumes: bool = False
    database_url: str = ""
    app_access_key: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            developer_token=_req("GOOGLE_ADS_DEVELOPER_TOKEN"),
            client_id=_req("GOOGLE_ADS_CLIENT_ID"),
            client_secret=_req("GOOGLE_ADS_CLIENT_SECRET"),
            refresh_token=_req("GOOGLE_ADS_REFRESH_TOKEN"),
            login_customer_id=_req("GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
            customer_id=_req("GOOGLE_ADS_CUSTOMER_ID"),
            chunk_size=int(os.environ.get("CHUNK_SIZE", "1000")),
            cache_freshness_days=int(os.environ.get("CACHE_FRESHNESS_DAYS", "30")),
            historical_window_months=int(os.environ.get("HISTORICAL_WINDOW_MONTHS", "6")),
            store_monthly_volumes=os.environ.get("STORE_MONTHLY_VOLUMES", "false").lower() == "true",
            database_url=os.environ.get("DATABASE_URL", ""),
            app_access_key=os.environ.get("APP_ACCESS_KEY", ""),
        )

    def google_ads_credentials(self) -> dict:
        return {
            "developer_token": self.developer_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "login_customer_id": self.login_customer_id,
            "use_proto_plus": True,
        }
