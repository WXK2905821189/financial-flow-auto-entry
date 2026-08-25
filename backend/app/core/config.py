from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置：全部经环境变量 / .env 注入，禁止写死密钥或凭据。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "财务流水自动入账 · 数据中台"
    environment: str = "dev"

    # 数据库（独立部署，仅财务网段可访问）；决策 D7=A 轻量关系库 MySQL 8.0
    database_url: str = "mysql+pymysql://waterflow:waterflow@127.0.0.1:3306/waterflow?charset=utf8mb4"

    # 简版登录（D2=A）：JWT + 初始管理员
    jwt_secret: str = "CHANGE_ME_JWT_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 小时
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin123"

    # 银企直连服务（决策 D6 主路：模拟银行 API 跑通生产链路；真实凭据 D3 就绪后切换）
    bank_api_base_url: str = "http://127.0.0.1:8080"
    bank_api_sign_secret: str = "mock-bank-secret"  # 生产从环境变量注入，禁止写死真实密钥

    # 金蝶云星空 OpenAPI（D8=A）：第三方系统登录授权
    # 五要素 = base_url / app_id / app_secret / acct_id / user_name（对应官方 K3CloudApiSdk.InitConfig）
    kingdee_base_url: str = ""
    kingdee_app_id: str = ""
    kingdee_app_secret: str = ""
    kingdee_acct_id: str = ""
    kingdee_user_name: str = ""
    kingdee_lcid: int = 2052        # 账套语系，默认 2052（简体中文）
    kingdee_org_num: int = 0        # 组织编码，启用多组织时配置
    kingdee_timeout: int = 30
    # 凭据未就绪时走 Mock 推送（9/16 链路打通演示），上线前置 false
    kingdee_mock_enabled: bool = True

    # 复核规则阈值（人民币，超过该金额转人工复核；规则 R004）
    review_amount_threshold: Decimal = Decimal("100000")

    # 校验通过后是否自动通过（false=全部转人工复核）
    auto_pass_enabled: bool = True

    def model_post_init(self, __context) -> None:
        """生产环境强制密钥校验：禁止占位符/明文默认值。

        SECRET/签名密钥必须经环境变量或内网密钥服务注入，杜绝硬编码泄密。
        """
        if self.environment.strip().lower() != "prod":
            return

        placeholder_checks = [
            ("JWT_SECRET", self.jwt_secret, "CHANGE_ME_JWT_SECRET"),
            ("INITIAL_ADMIN_PASSWORD", self.initial_admin_password, "admin123"),
            ("BANK_API_SIGN_SECRET", self.bank_api_sign_secret, "mock-bank-secret"),
        ]
        missing = [
            name for name, value, placeholder in placeholder_checks
            if not value or value == placeholder
        ]
        if not self.kingdee_mock_enabled:
            for field in (
                "kingdee_base_url",
                "kingdee_app_id",
                "kingdee_app_secret",
                "kingdee_acct_id",
                "kingdee_user_name",
            ):
                if not getattr(self, field):
                    missing.append(field.upper())
        if missing:
            raise ValueError(
                "生产环境禁止占位符/明文密钥，必须经环境变量显式配置：" + ", ".join(missing)
            )
        if "CHANGE_ME" in self.database_url or "waterflow:waterflow" in self.database_url:
            raise ValueError("生产环境 DATABASE_URL 禁止使用默认/占位符口令")


settings = Settings()