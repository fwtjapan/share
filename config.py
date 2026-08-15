import os
from dotenv import load_dotenv

load_dotenv()


def _num(name, default, cast):
    """
    安全地把環境變數轉成數字。

    修正：原本直接 float()/int() 環境變數，只要值是空字串、帶百分號（5%）、
    帶千分位逗號（20,000）或帶小數點（20000.0），就會在 import 階段丟 ValueError，
    導致 gunicorn worker 完全開不起來（container 反覆重啟）。
    現在改成：轉不動就退回預設值，並印出警告，服務不會因此掛掉。
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    cleaned = str(raw).strip().replace(',', '').replace('%', '').replace('％', '')
    try:
        return cast(cleaned)
    except (ValueError, TypeError):
        print(f"[WARN] 環境變數 {name} 的值 '{raw}' 無法轉成數字，改用預設值 {default}")
        return default


def _require(name, hint):
    """必填的環境變數，缺少時給出明確可行動的錯誤訊息。"""
    val = os.getenv(name)
    if not val or not val.strip():
        raise RuntimeError(
            f"\n"
            f"========================================\n"
            f"啟動失敗：環境變數 {name} 未設定\n"
            f"{hint}\n"
            f"請到 Zeabur 的 Environment Variables 頁面設定後重新部署。\n"
            f"========================================\n"
        )
    return val.strip()


class Config:
    # ---------- Supabase ----------
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    # 注意：必須使用 secret key（sb_secret_... 開頭，舊稱 service_role key）。
    # publishable / anon key 會受 Row Level Security 限制，寫入時會出現
    # "new row violates row-level security policy" 錯誤。
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

    # ---------- Shopify ----------
    SHOPIFY_SHOP_DOMAIN = os.getenv('SHOPIFY_SHOP_DOMAIN')
    SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
    SHOPIFY_WEBHOOK_SECRET = os.getenv('SHOPIFY_WEBHOOK_SECRET')

    # ---------- App Settings ----------
    # 修正：原本預設值是 'dev-secret-key'，這個字串公開在 GitHub repo 裡。
    # 任何人都能用它簽出一張管理員 session cookie，完全繞過登入。
    # 因此改成必填，沒設定就不讓服務啟動。
    SECRET_KEY = _require(
        'SECRET_KEY',
        "用途：加密簽署登入 session。沒設定的話任何人都能偽造管理員登入。\n"
        "產生方式：python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

    DEFAULT_COMMISSION_RATE = _num('DEFAULT_COMMISSION_RATE', 5.0, float)
    COOKIE_DAYS = _num('COOKIE_DAYS', 30, lambda s: int(float(s)))
    MIN_PAYOUT_JPY = _num('MIN_PAYOUT_JPY', 20000, lambda s: int(float(s)))

    # ---------- 短網址設定 ----------
    SHORT_URL_DOMAIN = os.getenv('SHORT_URL_DOMAIN', 'https://go.goyoulink.com').rstrip('/')
    REDIRECT_TARGET = os.getenv('REDIRECT_TARGET', 'https://goyoutati.com').rstrip('/')

    # ---------- Admin ----------
    # 修正：原本預設 admin / admin，漏設環境變數等於後台完全公開。
    ADMIN_USERNAME = _require(
        'ADMIN_USERNAME',
        "用途：管理後台登入帳號。請勿使用 admin。"
    )
    ADMIN_PASSWORD = _require(
        'ADMIN_PASSWORD',
        "用途：管理後台登入密碼。請使用高強度密碼，勿使用 admin。"
    )

    # ---------- 歸因設定 ----------
    # 是否允許「折扣碼剛好等於某人的推薦碼」就歸因給他。
    # 預設關閉：這個模糊比對會導致佣金誤發，也可能被惡意利用
    #（把自己的推薦碼設成熱門折扣碼字串來竊取他人業績）。
    ENABLE_DISCOUNT_CODE_ATTRIBUTION = os.getenv(
        'ENABLE_DISCOUNT_CODE_ATTRIBUTION', 'false'
    ).strip().lower() in ('1', 'true', 'yes', 'on')
