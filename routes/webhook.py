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
    """
    驗證 Shopify Webhook 簽名。

    修正（重要安全問題）：原本在 SHOPIFY_WEBHOOK_SECRET 未設定時直接 return True，
    也就是「沒設 secret 就全部放行」。因為 webhook 網址是公開的，
    這代表任何人都能 curl 兩次就偽造一筆數百萬日圓的假訂單並確認出貨，
    憑空產生真實的佣金負債。

    現在改成 fail-closed：沒有 secret 就一律拒絕。
    """
    if not Config.SHOPIFY_WEBHOOK_SECRET:
        print("[FATAL] SHOPIFY_WEBHOOK_SECRET 未設定，拒絕所有 webhook 請求。"
              "請到 Zeabur 環境變數設定後重新部署。")
        return False

    if not hmac_header:
        return False

    digest = hmac.new(
        Config.SHOPIFY_WEBHOOK_SECRET.encode('utf-8'),
        data,
        hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest).decode('utf-8')

    return hmac.compare_digest(computed_hmac, hmac_header)


def _safe_float(value, default=0.0):
    """
    安全轉換金額。

    修正：原本 float(order_data.get('total_price', 0)) 在 total_price 為
    JSON null、空字串、或帶千分位字串（"1,000"）時都會丟例外造成 500。
    注意 .get(key, 0) 的預設值只在 key 完全不存在時生效，
    key 存在但值是 null 時照樣拿到 None。
    Shopify 收到 500 會反覆重試該 webhook 長達 48 小時，
    而該筆真實訂單的分潤會永久漏記。
    """
    if value is None:
        return default
    try:
        return float(str(value).replace(',', '').strip())
    except (ValueError, TypeError):
        return default


def extract_ref_code(order_data):
    """從訂單中提取推薦碼"""

    # 方法 1：從 note_attributes 中找（Cart Attributes）
    # 修正：用 `or []`，因為值可能是 JSON null，直接迭代會丟 TypeError
    note_attributes = order_data.get('note_attributes') or []
    for attr in note_attributes:
        if isinstance(attr, dict) and attr.get('name') in ['ref', 'referral_code', 'affiliate']:
            value = attr.get('value')
            if value:
                return value

    # 方法 2：從 discount_codes 中找
    # 修正：這是拿「任意折扣碼」去撞「推薦碼」的模糊比對。若某個一般折扣碼
    # 剛好等於某位業者的推薦碼（推薦碼可自訂、常是好記短字），所有用該折扣碼
    # 的訂單都會被誤歸因給他；也可能被惡意利用（把自己的推薦碼設成熱門折扣碼
    # 字串來竊取他人業績）。因此改為預設關閉，需明確設定環境變數才啟用。
    if Config.ENABLE_DISCOUNT_CODE_ATTRIBUTION:
        discount_codes = order_data.get('discount_codes') or []
        for discount in discount_codes:
            if not isinstance(discount, dict):
                continue
            code = discount.get('code', '')
            if not code:
                continue
            affiliate = get_affiliate_by_ref_code(code)
            if affiliate:
                return code

    # 方法 3：從 order note 中找
    note = order_data.get('note') or ''
    if note:
        for part in str(note).split():
            if part.startswith('ref:'):
                return part[4:]

    # 方法 4：從 landing_site 中找 ref 參數
    landing_site = order_data.get('landing_site') or ''
    if landing_site and 'ref=' in landing_site:
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(landing_site)
            params = parse_qs(parsed.query)
            if 'ref' in params:
                return params['ref'][0]
        except Exception:
            pass

    return None


@webhook_bp.route('/shopify/orders/create', methods=['POST'])
def handle_order_create():
    """處理新訂單 Webhook"""

    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401

    order_data = request.get_json(silent=True)

    if not order_data:
        return jsonify({'error': 'No data'}), 400

    ref_code = extract_ref_code(order_data)

    if not ref_code:
        # 修正：原本這裡完全靜默。歸因失敗是這個系統最重要的失效模式
        #（代購業者該拿的佣金沒算到，而且沒有任何錯誤紀錄可追），
        # 所以改成留下 log，方便日後稽核「有點擊卻無歸因」的落差。
        print(f"[ATTRIBUTION MISS] 訂單 {order_data.get('name')} "
              f"(id={order_data.get('id')}) 找不到推薦碼，未建立分潤紀錄。"
              f" note_attributes={order_data.get('note_attributes')}"
              f" landing_site={order_data.get('landing_site')}")
        return jsonify({'status': 'ok', 'message': 'No referral code'}), 200

    affiliate = get_affiliate_by_ref_code(ref_code)

    if not affiliate:
        print(f"[ATTRIBUTION MISS] 訂單 {order_data.get('name')} 的推薦碼 "
              f"'{ref_code}' 查無對應業者。")
        return jsonify({'status': 'ok', 'message': 'Invalid referral code'}), 200

    if affiliate.get('status') != 'active':
        return jsonify({'status': 'ok', 'message': 'Affiliate inactive'}), 200

    shopify_order_id = str(order_data.get('id'))
    existing = get_order_by_shopify_id(shopify_order_id)

    if existing:
        return jsonify({'status': 'ok', 'message': 'Order already exists'}), 200

    order = create_referral_order(
        affiliate_id=affiliate['id'],
        shopify_order_id=shopify_order_id,
        order_number=order_data.get('name', ''),
        order_total=_safe_float(order_data.get('total_price')),
        currency=order_data.get('currency') or 'JPY',
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

    order_data = request.get_json(silent=True)

    if not order_data:
        return jsonify({'error': 'No data'}), 400

    shopify_order_id = str(order_data.get('id'))
    existing = get_order_by_shopify_id(shopify_order_id)

    if existing and existing.get('status') == 'pending':
        result = update_order_status(existing['id'], 'confirmed')
        if result is None:
            # 修正：原本不檢查回傳值，一律回 200。若更新失敗（網路/PostgREST 錯誤），
            # Shopify 不會重送，訂單會永遠停在待確認。改成回 500 讓 Shopify 重試。
            print(f"[ERROR] 訂單 {shopify_order_id} 確認失敗，回 500 讓 Shopify 重送")
            return jsonify({'error': 'Failed to confirm order'}), 500
        return jsonify({'status': 'ok', 'message': 'Order confirmed'}), 200

    return jsonify({'status': 'ok', 'message': 'No action needed'}), 200


@webhook_bp.route('/shopify/orders/cancelled', methods=['POST'])
def handle_order_cancelled():
    """處理訂單取消 Webhook"""

    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401

    order_data = request.get_json(silent=True)

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
    """
    處理退款 Webhook

    修正：原本對任何金額的退款都把整筆訂單標記為 refunded 並扣全額佣金。
    Shopify 的 refunds/create 對「部分退款」同樣會觸發，所以
    ¥10,000 訂單只退 ¥300 運費時，佣金會整整扣掉全額（應只扣按比例的部分）。
    現在改成依實際退款金額按比例回沖，只有全額退款才改狀態。
    """

    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    if not verify_shopify_webhook(request.data, hmac_header):
        return jsonify({'error': 'Invalid signature'}), 401

    refund_data = request.get_json(silent=True)

    if not refund_data:
        return jsonify({'error': 'No data'}), 400

    shopify_order_id = str(refund_data.get('order_id'))
    existing = get_order_by_shopify_id(shopify_order_id)

    if not existing:
        return jsonify({'status': 'ok', 'message': 'No action needed'}), 200

    # 計算這次實際退了多少錢
    refund_amount = 0.0
    for txn in (refund_data.get('transactions') or []):
        if isinstance(txn, dict) and txn.get('kind') in (None, 'refund'):
            refund_amount += _safe_float(txn.get('amount'))

    order_total = _safe_float(existing.get('order_total'))

    from models import apply_refund
    result = apply_refund(existing['id'], refund_amount, order_total)

    return jsonify({
        'status': 'ok',
        'message': 'Refund processed',
        'refund_amount': refund_amount,
        'fully_refunded': bool(result and result.get('fully_refunded')),
    }), 200


# 測試用 endpoint
@webhook_bp.route('/test', methods=['GET', 'POST'])
def test_webhook():
    """測試 Webhook 是否正常運作"""
    return jsonify({
        'status': 'ok',
        'message': 'Webhook endpoint is working',
        'signature_verification': 'enabled' if Config.SHOPIFY_WEBHOOK_SECRET else 'MISSING SECRET - all webhooks rejected',
    }), 200
