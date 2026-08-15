import os

from flask import Flask, render_template
from config import Config
from models import init_supabase, get_supabase
from routes import redirect_bp, webhook_bp, admin_bp, affiliate_bp
from routes.home import home_bp

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# 讓 Config 的設定也進到 app.config。
# 修正：Flask 會自動把 app.config 注入模板成 `config` 變數，
# 若哪天某個路由忘了傳 config=Config，模板不會報「變數未定義」，
# 而是拿到 Flask 自己的 config 物件並丟出誤導性的錯誤訊息。
app.config.from_object(Config)

# Session cookie 安全性設定
# 修正：原本完全沒設定，session cookie 可被跨站請求帶出（CSRF）、
# 也可能在 HTTP 明文連線中被竊取。
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True,
)

# 初始化 Supabase
# 修正：原本這行若丟例外（URL 打錯、key 格式不符、Supabase 暫停、
# 啟動瞬間網路不通），會讓整個 gunicorn worker 開不起來，連 /health 都不通。
# 現在包起來，讓服務一定能啟動；連線交給 get_supabase() 的 lazy init 重試。
try:
    init_supabase()
except Exception as e:
    print(f"[WARN] Supabase 啟動時初始化失敗，將於首次請求時重試：{e}")

# 註冊 Blueprints（順序重要！首頁要先註冊）
app.register_blueprint(home_bp)  # 首頁
app.register_blueprint(admin_bp)  # 管理後台 /admin
app.register_blueprint(affiliate_bp)  # 代購業者查詢 /partner
app.register_blueprint(webhook_bp, url_prefix='/webhook')  # Shopify Webhook
app.register_blueprint(redirect_bp)  # 短網址重新導向（放最後，避免攔截其他路由）


@app.route('/health')
def health_check():
    """
    健康檢查 endpoint。

    修正：原本不管資料庫通不通都回 200，導致「Supabase 變數沒設好」
    這種情況下服務看起來完全正常，但短網址默默不記錄點擊、
    後台一筆資料都沒有，分潤資料無聲流失。
    """
    db_ok = False
    try:
        db_ok = get_supabase() is not None
    except Exception:
        db_ok = False

    payload = {'status': 'ok' if db_ok else 'degraded', 'db': db_ok}
    return payload, (200 if db_ok else 503)


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='頁面不存在'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', message='伺服器錯誤'), 500


if __name__ == '__main__':
    # 修正：原本寫死 debug=True。若有人直接 python app.py 跑在對外機器上，
    # Werkzeug debugger 會開放遠端執行程式碼。改成由環境變數控制，預設關閉。
    debug_mode = os.getenv('FLASK_DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
