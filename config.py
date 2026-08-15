import os
import secrets

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


def _warn(name, hint):
    """
    缺少時大聲警告，但「不」讓服務掛掉。

    設計理由：這個服務有兩條完全不需要後台帳密的關鍵路徑 ——
    短網址導向（/<short_code>）與 Shopify webhook。
    若因為後台帳密沒設就讓整個 container 開不起來，
    等於顧客點推廣連結會連不上、Shopify 送來的訂單通知全部遺失，
    那是拿金流去賭一個設定問題，代價遠大於好處。

    所以改成：服務照常啟動，但把不安全的狀態明確標記出來，
    由呼叫端（例如 admin 登入）自行拒絕。
    """
    val = os.getenv(name)
    if not val or not val.strip():
        print(f"[SECURITY WARNING] 環境變數 {name} 未設定。{hint}")
        return None
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
    # 原本預設值是 'dev-secret-key'，這個字串公開在 GitHub repo 裡，
    # 任何人都能用它簽出一張管理員 session cookie，完全繞過登入。
    #
    # 現在改成：沒設定就「隨機產生一把」。服務照常啟動、短網址與 webhook
    # 完全不受影響，但因為每次重新部署金鑰都不同，登入狀態會失效
    #（需要重新登入後台）。這是安全且不會中斷服務的折衷。
    _secret = _warn(
        'SECRET_KEY',
        "已改用隨機金鑰，服務正常運作，但每次重新部署都需要重新登入後台。"
        " 建議設定固定值：python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
    SECRET_KEY = _secret or secrets.token_hex(32)

    DEFAULT_COMMISSION_RATE = _num('DEFAULT_COMMISSION_RATE', 5.0, float)
    COOKIE_DAYS = _num('COOKIE_DAYS', 30, lambda s: int(float(s)))
    MIN_PAYOUT_JPY = _num('MIN_PAYOUT_JPY', 20000, lambda s: int(float(s)))

    # ---------- 短網址設定 ----------
    SHORT_URL_DOMAIN = os.getenv('SHORT_URL_DOMAIN', 'https://go.goyoulink.com').rstrip('/')
    REDIRECT_TARGET = os.getenv('REDIRECT_TARGET', 'https://goyoutati.com').rstrip('/')

    # ---------- Admin ----------
    # 原本預設 admin / admin，漏設環境變數等於後台完全公開。
    # 現在改成：沒設定時服務照常啟動（短網址、webhook 不受影響），
    # 但 ADMIN_CONFIGURED 為 False，後台登入會直接拒絕並顯示設定指引。
    ADMIN_USERNAME = _warn(
        'ADMIN_USERNAME',
        "管理後台將暫時無法登入（短網址與 webhook 不受影響）。請設定後台登入帳號。"
    )
    ADMIN_PASSWORD = _warn(
        'ADMIN_PASSWORD',
        "管理後台將暫時無法登入（短網址與 webhook 不受影響）。請設定高強度密碼。"
    )

    # 後台是否已正確設定。刻意把 admin/admin 這組舊預設值也視為未設定，
    # 避免有人沿用它而不自知。
    ADMIN_CONFIGURED = bool(
        ADMIN_USERNAME and ADMIN_PASSWORD
        and not (ADMIN_USERNAME == 'admin' and ADMIN_PASSWORD == 'admin')
    )

    # ---------- 歸因設定 ----------
    # 是否允許「折扣碼剛好等於某人的推薦碼」就歸因給他。
    # 預設關閉：這個模糊比對會導致佣金誤發，也可能被惡意利用
    #（把自己的推薦碼設成熱門折扣碼字串來竊取他人業績）。
    ENABLE_DISCOUNT_CODE_ATTRIBUTION = os.getenv(
        'ENABLE_DISCOUNT_CODE_ATTRIBUTION', 'false'
    ).strip().lower() in ('1', 'true', 'yes', 'on')
