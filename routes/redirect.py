import re

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

# 修正：product_path 原本未經任何驗證就接到 REDIRECT_TARGET 後面，
# 實測 /ab/%09//evil.com 和 /ab/..%2f..%2fevil.com 都會出現在 Location 標頭，
# 可用於釣魚（顯示你的短網址卻導去別的路徑）。
# 現在只允許安全的路徑字元，且不允許 // 或 .. 這類逃逸序列。
_SAFE_PATH = re.compile(r'^[A-Za-z0-9\-._~/]+$')


def _is_safe_product_path(path: str) -> bool:
    if not path or len(path) > 200:
        return False
    if not _SAFE_PATH.match(path):
        return False
    if '..' in path or '//' in path or path.startswith('/'):
        return False
    return True


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
        return redirect(f"{Config.REDIRECT_TARGET}?ref={affiliate['ref_code']}")

    target_url = f"{Config.REDIRECT_TARGET}/{product_path}"
    record_click(
        affiliate_id=affiliate['id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.headers.get('Referer'),
        landed_url=target_url,
        source=_source_from_request()
    )

    return redirect(f"{target_url}?ref={affiliate['ref_code']}")
