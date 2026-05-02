from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    wsl_distro: str = "Ubuntu"
    wsl_home: str = "home"
    wsl_user: str = ""

    db_path: Path = Path("data/token_statistic.db")
    collector_state_path: Path = Path("data/collector_state.json")

    poll_interval_seconds: int = 5
    host: str = "127.0.0.1"
    port: int = 8000

    frontend_dist: Path = Path("frontend/dist")

    model_config = {"env_prefix": "TOKEN_STAT_"}

    @property
    def wsl_root(self) -> str:
        return f"\\\\wsl$\\{self.wsl_distro}"

    @property
    def wsl_home_path(self) -> str:
        user = self.wsl_user or "*"
        return f"{self.wsl_root}\\{self.wsl_home}\\{user}"


settings = Settings()
