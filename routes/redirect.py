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


@redirect_bp.route('/<short_code>')
def redirect_short(short_code):
    """短網址重新導向"""
    affiliate = get_affiliate_by_short_code(short_code)
    
    if not affiliate:
        return redirect(Config.REDIRECT_TARGET)
    
    # 取得來源參數
    source_code = request.args.get('s', '').lower()
    source = SOURCE_CODES.get(source_code, None)
    
    # 記錄點擊
    record_click(
        affiliate_id=affiliate['id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.headers.get('Referer'),
        landed_url=Config.REDIRECT_TARGET,
        source=source
    )
    
    # 重新導向到目標網站，帶上推薦碼
    target_url = f"{Config.REDIRECT_TARGET}?ref={affiliate['ref_code']}"
    
    return redirect(target_url)


@redirect_bp.route('/<short_code>/<path:product_path>')
def redirect_product(short_code, product_path):
    """商品頁面短網址重新導向"""
    affiliate = get_affiliate_by_short_code(short_code)
    
    if not affiliate:
        return redirect(Config.REDIRECT_TARGET)
    
    # 取得來源參數
    source_code = request.args.get('s', '').lower()
    source = SOURCE_CODES.get(source_code, None)
    
    # 記錄點擊
    target_url = f"{Config.REDIRECT_TARGET}/{product_path}"
    record_click(
        affiliate_id=affiliate['id'],
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        referer=request.headers.get('Referer'),
        landed_url=target_url,
        source=source
    )
    
    # 重新導向到商品頁面，帶上推薦碼
    target_url = f"{Config.REDIRECT_TARGET}/{product_path}?ref={affiliate['ref_code']}"
    
    return redirect(target_url)
