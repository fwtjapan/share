from flask import Blueprint, request, jsonify
from models import (
    get_affiliate_by_ref_code, 
    create_referral_order, 
    get_order_by_shopify_id,
    update_order_status
)
from config import Config
import hmac
import hashlib
import base64

webhook_bp = Blueprint('webhook', __name__)


def verify_shopify_webhook(data, hmac_header):
    """驗證 Shopify Webhook 簽名"""
    if not Config.SHOPIFY_WEBHOOK_SECRET:
        # 開發模式，跳過驗證
        return True
    
    digest = hmac.new(
        Config.SHOPIFY_WEBHOOK_SECRET.encode('utf-8'),
        data,
        hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest).decode('utf-8')
    
    return hmac.compare_digest(computed_hmac, hmac_header)


def extract_ref_code(order_data):
    """從訂單中提取推薦碼"""
    
    # 方法 1：從 note_attributes 中找（Cart Attributes）
    note_attributes = order_data.get('note_attributes', [])
    for attr in note_attributes:
        if attr.get('name') in ['ref', 'referral_code', 'affiliate']:
            return attr.get('value')
    
    # 方法 2：從 discount_codes 中找（如果推薦碼就是折扣碼）
    discount_codes = order_data.get('discount_codes', [])
    for discount in discount_codes:
        code = discount.get('code', '')
        # 檢查這個折扣碼是否是某個代購業者的 ref_code
        affiliate = get_affiliate_by_ref_code(code)
        if affiliate:
            return code
    
    # 方法 3：從 order note 中找
    note = order_data.get('note', '')
    if note:
        # 簡單解析，例如 "ref:alice123"
        for part in note.split():
            if part.startswith('ref:'):
                return part[4:]
    
    # 方法 4：從 landing_site 或 referring_site 中找 ref 參數
    landing_site = order_data.get('landing_site', '')
    if landing_site and 'ref=' in landing_site:
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(landing_site)
            params = parse_qs(parsed.query)
            if 'ref' in params:
                return params['ref'][0]
        except:
            pass
    
    return None


@webhook_bp.route('/shopify/orders/create', methods=['POST'])
def handle_order_create():
    """處理新訂單 Webhook"""
    
    # 驗證 Webhook
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401
    
    order_data = request.get_json()
    
    if not order_data:
        return jsonify({'error': 'No data'}), 400
    
    # 提取推薦碼
    ref_code = extract_ref_code(order_data)
    
    if not ref_code:
        # 沒有推薦碼，不是分潤訂單
        return jsonify({'status': 'ok', 'message': 'No referral code'}), 200
    
    # 查詢代購業者
    affiliate = get_affiliate_by_ref_code(ref_code)
    
    if not affiliate:
        return jsonify({'status': 'ok', 'message': 'Invalid referral code'}), 200
    
    if affiliate['status'] != 'active':
        return jsonify({'status': 'ok', 'message': 'Affiliate inactive'}), 200
    
    # 檢查訂單是否已存在
    shopify_order_id = str(order_data.get('id'))
    existing = get_order_by_shopify_id(shopify_order_id)
    
    if existing:
        return jsonify({'status': 'ok', 'message': 'Order already exists'}), 200
    
    # 建立推薦訂單記錄
    order = create_referral_order(
        affiliate_id=affiliate['id'],
        shopify_order_id=shopify_order_id,
        order_number=order_data.get('name', ''),  # #1001
        order_total=float(order_data.get('total_price', 0)),
        currency=order_data.get('currency', 'JPY'),
        customer_email=order_data.get('email'),
        order_created_at=order_data.get('created_at')
    )
    
    return jsonify({
        'status': 'ok',
        'message': 'Referral order created',
        'order_id': order['id'] if order else None
    }), 200


@webhook_bp.route('/shopify/orders/fulfilled', methods=['POST'])
def handle_order_fulfilled():
    """處理訂單出貨 Webhook（確認佣金）"""
    
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401
    
    order_data = request.get_json()
    
    if not order_data:
        return jsonify({'error': 'No data'}), 400
    
    shopify_order_id = str(order_data.get('id'))
    existing = get_order_by_shopify_id(shopify_order_id)
    
    if existing and existing['status'] == 'pending':
        # 訂單已出貨，確認佣金
        update_order_status(existing['id'], 'confirmed')
        return jsonify({'status': 'ok', 'message': 'Order confirmed'}), 200
    
    return jsonify({'status': 'ok', 'message': 'No action needed'}), 200


@webhook_bp.route('/shopify/orders/cancelled', methods=['POST'])
def handle_order_cancelled():
    """處理訂單取消 Webhook"""
    
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401
    
    order_data = request.get_json()
    
    if not order_data:
        return jsonify({'error': 'No data'}), 400
    
    shopify_order_id = str(order_data.get('id'))
    existing = get_order_by_shopify_id(shopify_order_id)
    
    if existing:
        update_order_status(existing['id'], 'cancelled')
        return jsonify({'status': 'ok', 'message': 'Order cancelled'}), 200
    
    return jsonify({'status': 'ok', 'message': 'No action needed'}), 200


@webhook_bp.route('/shopify/refunds/create', methods=['POST'])
def handle_refund_create():
    """處理退款 Webhook"""
    
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401
    
    refund_data = request.get_json()
    
    if not refund_data:
        return jsonify({'error': 'No data'}), 400
    
    # 退款資料中的 order_id
    shopify_order_id = str(refund_data.get('order_id'))
    existing = get_order_by_shopify_id(shopify_order_id)
    
    if existing:
        update_order_status(existing['id'], 'refunded')
        return jsonify({'status': 'ok', 'message': 'Order refunded'}), 200
    
    return jsonify({'status': 'ok', 'message': 'No action needed'}), 200


# 測試用 endpoint
@webhook_bp.route('/test', methods=['GET', 'POST'])
def test_webhook():
    """測試 Webhook 是否正常運作"""
    return jsonify({
        'status': 'ok',
        'message': 'Webhook endpoint is working'
    }), 200
