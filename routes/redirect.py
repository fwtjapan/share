from urllib.parse import quote

from flask import Blueprint, redirect, request
from models import get_affiliate_by_short_code, record_click
from config import Config

redirect_bp = Blueprint('redirect', __name__)

# 來源代碼對照
SOURCE_CODES = {
    'fb': 'facebook',
    'ig': 'instagram',
    'th': 'threads',
    'yt': 'youtube',
    'tt': 'tiktok',
    'tw': 'twitter',
    'li': 'line',
    'em': 'email',
    'ws': 'website'
}

# 修正：`/<short_code>` 是根目錄萬用路由，會把 /favicon.ico、/robots.txt、
# /apple-touch-icon.png 等瀏覽器自動請求全部吃掉，每一個都打一次 Supabase 查詢。
# 在單一 worker 上會實際吃掉吞吐量，log 也會被假的短網址查詢洗版。
_IGNORED_PATHS = {
    'favicon.ico', 'robots.txt', 'sitemap.xml', 'apple-touch-icon.png',
    'apple-touch-icon-precomposed.png', 'browserconfig.xml',
    'manifest.json', 'sw.js', 'ads.txt', '.well-known',
}

# product_path 若未經驗證就接到 REDIRECT_TARGET 後面，可以用
# /ab/%09//evil.com 或 /ab/..%2f..%2fevil.com 讓 Location 標頭指向非預期位置，
# 用於釣魚（顯示你的短網址卻導去別的路徑）。
#
# 【重要修正】先前這裡用字元白名單 ^[A-Za-z0-9\-._~/]+$ 做檢查，
# 但這個商店的商品 handle 幾乎都是中文（例如 products/日本龍角散直服-顆粒-境內版），
# Flask 會先把網址解碼再交給路由，中文字元不在白名單內 —— 結果是
# 「每一個商品推廣連結都被擋掉，一律退回首頁」，等於整個商品連結功能全毀。
#
# 改用結構性檢查：不限制字元集（Unicode 一律放行），只擋真正危險的樣式，
# 並在組網址時用 quote() 重新做正確的百分比編碼。
_CONTROL_CHARS = {chr(i) for i in range(32)} | {chr(127)}


def _is_safe_product_path(path: str) -> bool:
    """只擋路徑逃逸與偽造網址，不限制語言字元。"""
    if not path or len(path) > 300:
        return False
    # 路徑逃逸 / protocol-relative / Windows 路徑分隔
    if '..' in path or '//' in path or path.startswith('/') or '\\' in path:
        return False
    # 控制字元（含 %09 這類，解碼後會是 tab）
    if any(ch in _CONTROL_CHARS for ch in path):
        return False
    # 冒號會讓它看起來像另一個 scheme（http://evil）
    if ':' in path:
        return False
    return True


def _build_target(product_path: str) -> str:
    """把商品路徑安全地接到目標網站後面，並正確編碼非 ASCII 字元。"""
    # safe='/' 保留路徑分隔符號，其餘（中文、空白等）轉成百分比編碼
    encoded = quote(product_path, safe='/')
    return f"{Config.REDIRECT_TARGET}/{encoded}"


def _source_from_request():
    source_code = (request.args.get('s') or '').lower()
    return SOURCE_CODES.get(source_code)


@redirect_bp.route('/<short_code>')
def redirect_short(short_code):
    """短網址重新導向"""
    if short_code in _IGNORED_PATHS or '.' in short_code:
        return '', 404

    affiliate = get_affiliate_by_short_code(short_code)

    if not affiliate:
        return redirect(Config.REDIRECT_TARGET)

    record_click(
        affiliate_id=affiliate['id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.headers.get('Referer'),
        landed_url=Config.REDIRECT_TARGET,
        source=_source_from_request()
    )

    target_url = f"{Config.REDIRECT_TARGET}?ref={affiliate['ref_code']}"

    return redirect(target_url)


@redirect_bp.route('/<short_code>/<path:product_path>')
def redirect_product(short_code, product_path):
    """商品頁面短網址重新導向"""
    affiliate = get_affiliate_by_short_code(short_code)

    if not affiliate:
        return redirect(Config.REDIRECT_TARGET)

    if not _is_safe_product_path(product_path):
        # 路徑不安全就退回首頁，仍然帶上推薦碼，不影響歸因
        print(f"[REDIRECT] 拒絕不安全的商品路徑: {product_path!r}")
        return redirect(f"{Config.REDIRECT_TARGET}?ref={affiliate['ref_code']}")

    target_url = _build_target(product_path)
    record_click(
        affiliate_id=affiliate['id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.headers.get('Referer'),
        landed_url=target_url,
        source=_source_from_request()
    )

    return redirect(f"{target_url}?ref={affiliate['ref_code']}")
