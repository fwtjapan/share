from flask import Flask, render_template
from config import Config
from models import init_supabase
from routes import redirect_bp, webhook_bp, admin_bp, affiliate_bp
from routes.home import home_bp

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# 初始化 Supabase
init_supabase()

# 註冊 Blueprints（順序重要！首頁要先註冊）
app.register_blueprint(home_bp)  # 首頁
app.register_blueprint(admin_bp)  # 管理後台 /admin
app.register_blueprint(affiliate_bp)  # 代購業者查詢 /partner
app.register_blueprint(webhook_bp, url_prefix='/webhook')  # Shopify Webhook
app.register_blueprint(redirect_bp)  # 短網址重新導向（放最後，避免攔截其他路由）


@app.route('/health')
def health_check():
    """健康檢查 endpoint"""
    return {'status': 'ok'}, 200


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='頁面不存在'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', message='伺服器錯誤'), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
