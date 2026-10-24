"""KT-OMS 全局配置（Pydantic Settings，12-Factor：环境变量/.env 注入）"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KTOMS_", extra="ignore")

    # 应用
    app_name: str = "KT-OMS"
    env: str = "dev"                     # dev / test / staging / prod
    debug: bool = True
    api_prefix: str = "/api/v1"

    # MySQL（本地 docker compose：deploy/docker-compose.yml，端口 3308）
    # 多 schema：主连接默认 oms_base，跨域查询用 schema 前缀（DB-00 §2 跨 schema 规则：禁跨域 JOIN，报表豁免）
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3308
    mysql_user: str = "root"
    mysql_password: str = "ktoms_dev_2026"
    mysql_db: str = "oms_base"
    mysql_pool_size: int = 10
    mysql_max_overflow: int = 20
    mysql_echo: bool = False

    # Redis（库存预占 Lua / 缓存 / 分布式锁）
    redis_url: str = "redis://127.0.0.1:6380/0"

    # RabbitMQ（outbox 投递 / 事件消费）
    rabbitmq_url: str = "amqp://ktoms:ktoms_dev_2026@127.0.0.1:5673/"

    # 安全
    secret_key: str = "dev-only-change-me"   # 生产走 KMS（D01.05 信封加密主密钥）
    access_token_expire_minutes: int = 480

    @property
    def sqlalchemy_uri(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
