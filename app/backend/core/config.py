import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.engine import URL


def load_environment() -> dict[str, str | None]:
    env_file = Path(__file__).resolve().parents[2] / '.env'
    return {**dotenv_values(env_file), **os.environ}


class DatabaseSettings(BaseModel):
    host: str = Field(min_length=1)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1)
    password: SecretStr
    database: str = Field(min_length=1)

    @property
    def url(self) -> URL:
        return URL.create(
            'mysql+pymysql',
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database,
            query={'charset': 'utf8mb4'},
        )

    @classmethod
    def load(cls) -> 'DatabaseSettings':
        values = load_environment()
        required = ('MYSQL_HOST', 'MYSQL_USERNAME', 'MYSQL_PASSWORD', 'MYSQL_DATABASE')
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise RuntimeError('请在 app/.env 或环境变量中设置 ' + ', '.join(missing))
        try:
            return cls(
                host=(values.get('MYSQL_HOST') or '').strip(),
                port=int(values.get('MYSQL_PORT') or '3306'),
                username=(values.get('MYSQL_USERNAME') or '').strip(),
                password=SecretStr(values.get('MYSQL_PASSWORD') or ''),
                database=(values.get('MYSQL_DATABASE') or '').strip(),
            )
        except ValueError:
            raise RuntimeError('MySQL 配置无效：主机、用户名和数据库不能为空，端口必须为 1–65535') from None


class Settings(BaseModel):
    api_key: SecretStr
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-flash'
    timeout: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)

    @classmethod
    def load(cls) -> 'Settings':
        values = load_environment()
        api_key = (values.get('DEEPSEEK_API_KEY') or '').strip()
        base_url = (values.get('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com').strip().rstrip('/')
        model = (values.get('DEEPSEEK_MODEL') or 'deepseek-flash').strip()
        if not api_key:
            raise RuntimeError('请在 app/.env 或环境变量中设置 DEEPSEEK_API_KEY')
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise RuntimeError('DEEPSEEK_BASE_URL 不是有效的 HTTPS 地址') from None
        if url.scheme != 'https' or not url.host or url.userinfo or url.query or url.fragment:
            raise RuntimeError('DEEPSEEK_BASE_URL 必须是无凭据、查询参数和片段的 HTTPS 地址')
        try:
            timeout = float(values.get('DEEPSEEK_TIMEOUT_SECONDS') or '60')
            return cls(api_key=SecretStr(api_key), base_url=base_url, model=model, timeout=timeout)
        except ValueError:
            raise RuntimeError('DEEPSEEK_TIMEOUT_SECONDS 必须是 0 到 600 之间的有限秒数') from None
