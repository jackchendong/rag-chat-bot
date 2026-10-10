import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    api_key: SecretStr
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-flash'
    timeout: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)

    @classmethod
    def load(cls) -> 'Settings':
        env_file = Path(__file__).resolve().parents[2] / '.env'
        values = {**dotenv_values(env_file), **os.environ}
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
