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

    # 本地账号认证：短期访问 Cookie + 轮换刷新会话。前端、后端独立部署时
    # 通过 FRONTEND_ORIGINS 显式列出前端来源，禁止凭据 CORS 使用通配符。
    jwt_secret: str = "CHANGE_ME_JWT_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 480
    frontend_origins: str = "http://localhost:8000"
    auth_cookie_name: str = "wf_access"
    refresh_cookie_name: str = "wf_refresh"
    csrf_cookie_name: str = "wf_csrf"
    auth_cookie_samesite: str = "lax"
    auth_cookie_secure: bool = False
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin123"
    max_failed_logins: int = 5
    login_lockout_minutes: int = 15

    # 独立部署时后端不托管前端静态文件；开发/演示环境可打开。
    serve_frontend_static: bool = True

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
        initial_password_kinds = sum(
            (
                any(char.islower() for char in self.initial_admin_password),
                any(char.isupper() for char in self.initial_admin_password),
                any(char.isdigit() for char in self.initial_admin_password),
                any(not char.isalnum() for char in self.initial_admin_password),
            )
        )
        if len(self.initial_admin_password) < 12 or initial_password_kinds < 3:
            raise ValueError("生产环境 INITIAL_ADMIN_PASSWORD 至少 12 位，且须包含至少三类字符")
        if not self.auth_cookie_secure:
            raise ValueError("生产环境 AUTH_COOKIE_SECURE 必须为 true")
        if self.serve_frontend_static:
            raise ValueError("生产环境 SERVE_FRONTEND_STATIC 必须为 false，前端需独立部署")
        if "*" in self.frontend_origins:
            raise ValueError("生产环境 FRONTEND_ORIGINS 不得使用通配符")
        if self.auth_cookie_samesite.lower() not in {"lax", "strict", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE 仅支持 lax/strict/none")

    @property
    def frontend_origins_list(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]


settings = Settings()
