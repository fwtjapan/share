from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from models import (
    get_affiliate_by_ref_code, get_affiliate_by_id, update_affiliate,
    get_orders_by_affiliate, get_payouts_by_affiliate, get_clicks_by_affiliate,
    get_affiliate_summary, get_clicks_by_source, normalize_url
)
from config import Config
import requests

affiliate_bp = Blueprint('affiliate', __name__, url_prefix='/partner')


def affiliate_required(f):
    """代購業者登入驗證裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('affiliate_id'):
            return redirect(url_for('affiliate.login'))
        return f(*args, **kwargs)
    return decorated_function


# Shopify Admin API 版本。
# 原本寫死 2024-01，該版本早已退役。Shopify 對退役版本會「向前遞補」由最舊的
# 可用版本服務，所以不會直接失敗，但行為可能與預期不同（欄位增刪、預設值改變）。
# Shopify 每季發一版、每版至少支援 12 個月，建議每年更新一次這個常數。
SHOPIFY_API_VERSION = '2026-01'


def search_shopify_graphql(query, max_results=20):
    """
    使用 Shopify GraphQL API 搜尋商品。

    回傳 (products, error_message)。

    修正：原本不論發生什麼錯誤都只 return []，前端一律顯示「找不到相關商品」。
    環境變數沒設、token 過期、權限不足、API 報錯——全都長得一模一樣，
    完全無法判斷problem 出在哪。現在會把真正的原因回報出來。
    """
    shop_domain = (Config.SHOPIFY_SHOP_DOMAIN or '').strip()
    access_token = (Config.SHOPIFY_ACCESS_TOKEN or '').strip()

    if not shop_domain:
        return [], '尚未設定 SHOPIFY_SHOP_DOMAIN（環境變數），無法連線到 Shopify'
    if not access_token:
        return [], '尚未設定 SHOPIFY_ACCESS_TOKEN（環境變數），無法連線到 Shopify'

    # 容錯：使用者可能填了 https:// 或結尾斜線
    shop_domain = shop_domain.replace('https://', '').replace('http://', '').rstrip('/')

    url = f"https://{shop_domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        'X-Shopify-Access-Token': access_token,
        'Content-Type': 'application/json'
    }

    graphql_query = """
    query searchProducts($query: String!, $first: Int!) {
        products(first: $first, query: $query) {
            edges {
                node {
                    id
                    title
                    handle
                    vendor
                    status
                    variants(first: 1) {
                        edges { node { price } }
                    }
                    media(first: 1) {
                        edges {
                            node {
                                preview { image { url } }
                            }
                        }
                    }
                }
            }
        }
    }
    """

    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                'query': graphql_query,
                'variables': {'query': query, 'first': min(max(max_results, 1), 50)}
            },
            timeout=15
        )
    except requests.exceptions.Timeout:
        return [], 'Shopify 回應逾時，請稍後再試'
    except Exception as e:
        print(f"[SHOPIFY] 連線失敗: {e}")
        return [], f'無法連線到 Shopify（{shop_domain}），請確認網域設定是否正確'

    # 針對常見狀態碼給出可行動的訊息
    if response.status_code == 401:
        return [], 'Shopify 拒絕存取（401）：SHOPIFY_ACCESS_TOKEN 無效或已失效'
    if response.status_code == 403:
        return [], ('Shopify 拒絕存取（403）：這組 Access Token 缺少 read_products 權限。'
                    '請到 Shopify 後台的 custom app 勾選 read_products 後重新安裝並更新 token')
    if response.status_code == 404:
        return [], (f'找不到 Shopify 商店（404）：請確認 SHOPIFY_SHOP_DOMAIN 是否正確，'
                    f'目前設定為 {shop_domain}（正確格式如 your-shop.myshopify.com）')
    if response.status_code != 200:
        print(f"[SHOPIFY] HTTP {response.status_code}: {response.text[:500]}")
        return [], f'Shopify 回應異常（HTTP {response.status_code}）'

    try:
        data = response.json()
    except Exception:
        return [], 'Shopify 回應格式異常，無法解析'

    if 'errors' in data:
        errs = data['errors']
        print(f"[SHOPIFY] GraphQL errors: {errs}")
        msg = ''
        if isinstance(errs, list) and errs:
            msg = errs[0].get('message', '') if isinstance(errs[0], dict) else str(errs[0])
        elif isinstance(errs, dict):
            msg = str(errs)
        # 權限不足時 Shopify 常以 GraphQL error 形式回傳
        if 'access' in msg.lower() or 'scope' in msg.lower() or 'permission' in msg.lower():
            return [], f'Shopify 權限不足：{msg}（請確認 Access Token 有 read_products 權限）'
        return [], f'Shopify 查詢失敗：{msg}'

    products = []
    edges = (data.get('data') or {}).get('products', {}).get('edges', []) or []
    total_seen = len(edges)

    for edge in edges:
        node = edge.get('node') or {}

        # 只顯示 active 商品（草稿/封存的不該推廣）
        if node.get('status') != 'ACTIVE':
            continue

        price = '0'
        variants = (node.get('variants') or {}).get('edges', [])
        if variants:
            price = (variants[0].get('node') or {}).get('price', '0')

        image_url = ''
        media = (node.get('media') or {}).get('edges', [])
        if media:
            preview = (media[0].get('node') or {}).get('preview') or {}
            image_url = (preview.get('image') or {}).get('url', '') or ''

        products.append({
            'id': node.get('id', ''),
            'title': node.get('title', ''),
            'handle': node.get('handle', ''),
            'price': price,
            'image': image_url,
            'vendor': node.get('vendor', ''),
            'url': f"{Config.REDIRECT_TARGET}/products/{node.get('handle', '')}"
        })

    # 有搜到東西但全被 ACTIVE 篩掉時，明確告知，不要讓人以為是壞掉
    if not products and total_seen > 0:
        return [], f'找到 {total_seen} 個相符商品，但都不是「有效（Active）」狀態，無法推廣'

    return products[:max_results], None


# ============================================
# 登入/登出
# ============================================

@affiliate_bp.route('/login', methods=['GET', 'POST'])
def login():
    """代購業者登入頁面"""
    if request.method == 'POST':
        ref_code = request.form.get('ref_code', '').strip()
        
        affiliate = get_affiliate_by_ref_code(ref_code)
        
        if affiliate and affiliate.get('status') == 'active':
            session['affiliate_id'] = affiliate['id']
            session['affiliate_ref_code'] = affiliate['ref_code']
            return redirect(url_for('affiliate.dashboard'))
        else:
            return render_template('affiliate/login.html', error='推薦碼無效或帳戶已停用')
    
    return render_template('affiliate/login.html')


@affiliate_bp.route('/logout')
def logout():
    """登出"""
    session.pop('affiliate_id', None)
    session.pop('affiliate_ref_code', None)
    return redirect(url_for('affiliate.login'))


# ============================================
# 使用說明
# ============================================

@affiliate_bp.route('/help')
def help_page():
    """
    代購業者使用說明。

    刻意不加 @affiliate_required：新加入的推廣夥伴在拿到推薦碼、還沒登入之前
    就需要看得懂怎麼開始，登入才看得到的說明對他們沒有意義。
    這頁不含任何個人資料，公開無妨。
    """
    return render_template('affiliate/help.html')


# ============================================
# 儀表板
# ============================================

@affiliate_bp.route('/')
@affiliate_bp.route('/dashboard')
@affiliate_required
def dashboard():
    """代購業者儀表板"""
    affiliate_id = session.get('affiliate_id')
    summary = get_affiliate_summary(affiliate_id)
    
    if not summary:
        return redirect(url_for('affiliate.logout'))
    
    recent_orders = get_orders_by_affiliate(affiliate_id, limit=5)
    
    return render_template('affiliate/dashboard.html', 
                           summary=summary, recent_orders=recent_orders, config=Config)


# ============================================
# 個人資料
# ============================================

@affiliate_bp.route('/profile', methods=['GET', 'POST'])
@affiliate_required
def profile():
    """個人資料編輯"""
    affiliate_id = session.get('affiliate_id')
    affiliate = get_affiliate_by_id(affiliate_id)
    
    if not affiliate:
        return redirect(url_for('affiliate.logout'))
    
    if request.method == 'POST':
        # 【重要修正】原本這裡無條件寫入五個社群欄位，但 profile.html 的表單
        # 根本沒有這些輸入框 —— request.form.get() 一律回傳 None，
        # 結果是「代購業者每次儲存個人資料，管理員幫他設定的社群連結就全被清空」。
        # 現在改成：只更新表單實際有送出的欄位，沒送出的一律不動。
        update_data = {}

        if 'email' in request.form:
            update_data['email'] = (request.form.get('email') or '').strip() or None

        for field in ('social_facebook', 'social_instagram', 'social_threads',
                      'social_youtube', 'social_tiktok'):
            if field in request.form:
                update_data[field] = normalize_url(request.form.get(field))

        if update_data:
            update_affiliate(affiliate_id, **update_data)
        
        affiliate = get_affiliate_by_id(affiliate_id)
        return render_template('affiliate/profile.html', affiliate=affiliate, success=True)
    
    return render_template('affiliate/profile.html', affiliate=affiliate)


# ============================================
# 訂單查詢
# ============================================

@affiliate_bp.route('/orders')
@affiliate_required
def orders():
    """訂單列表"""
    affiliate_id = session.get('affiliate_id')
    status_filter = request.args.get('status')
    
    orders = get_orders_by_affiliate(affiliate_id, status=status_filter, limit=100)
    affiliate = get_affiliate_by_id(affiliate_id)
    
    return render_template('affiliate/orders.html', orders=orders, 
                           affiliate=affiliate, status_filter=status_filter)


# ============================================
# 佣金記錄
# ============================================

@affiliate_bp.route('/payouts')
@affiliate_required
def payouts():
    """發放記錄"""
    affiliate_id = session.get('affiliate_id')
    
    payouts = get_payouts_by_affiliate(affiliate_id, limit=100)
    affiliate = get_affiliate_by_id(affiliate_id)
    
    return render_template('affiliate/payouts.html', payouts=payouts, 
                           affiliate=affiliate, config=Config)


# ============================================
# 推廣連結
# ============================================

@affiliate_bp.route('/links')
@affiliate_required
def links():
    """推廣連結頁面"""
    affiliate_id = session.get('affiliate_id')
    affiliate = get_affiliate_by_id(affiliate_id)

    # 修正：原本沒有 None 檢查（同檔案的 dashboard()、profile() 都有，只有這裡漏了）。
    # 當管理員刪掉該業者、或 Supabase 瞬間連線異常時（例外被 except 吞掉回傳 None），
    # 下一行的 affiliate['short_code'] 會丟 TypeError 造成 500。
    if not affiliate:
        return redirect(url_for('affiliate.logout'))

    short_url = f"{Config.SHORT_URL_DOMAIN}/{affiliate.get('short_code', '')}"
    direct_url = f"{Config.REDIRECT_TARGET}?ref={affiliate.get('ref_code', '')}"
    
    source_stats = get_clicks_by_source(affiliate_id)
    
    return render_template('affiliate/links.html', 
                           affiliate=affiliate, short_url=short_url, 
                           direct_url=direct_url, config=Config,
                           source_stats=source_stats)


# ============================================
# 商品搜尋 API
# ============================================

@affiliate_bp.route('/api/products/search')
@affiliate_required
def api_search_products():
    """搜尋 Shopify 商品（使用 GraphQL API）"""
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({'products': [], 'error': '請輸入至少 2 個字'})
    
    try:
        products, error = search_shopify_graphql(query, max_results=20)

        if error:
            # 把真正的失敗原因傳給前端顯示。
            # 修正前不論什麼錯誤都回空陣列，前端一律顯示「找不到相關商品」，
            # 導致「環境變數沒設」和「真的查無商品」完全無法分辨。
            return jsonify({'products': [], 'error': error})

        return jsonify({
            'products': products,
            'total_found': len(products),
            'shop_url': Config.REDIRECT_TARGET
        })

    except Exception as e:
        print(f"Error searching products: {e}")
        return jsonify({'products': [], 'error': f'搜尋時發生未預期的錯誤：{e}'})


# ============================================
# API endpoints
# ============================================

@affiliate_bp.route('/api/stats')
@affiliate_required
def api_stats():
    """取得統計數據 API"""
    affiliate_id = session.get('affiliate_id')
    summary = get_affiliate_summary(affiliate_id)
    return jsonify(summary)


@affiliate_bp.route('/api/orders')
@affiliate_required
def api_orders():
    """取得訂單列表 API"""
    affiliate_id = session.get('affiliate_id')
    orders = get_orders_by_affiliate(affiliate_id, limit=50)
    return jsonify(orders)


@affiliate_bp.route('/api/clicks')
@affiliate_required
def api_clicks():
    """取得點擊記錄 API"""
    affiliate_id = session.get('affiliate_id')
    clicks = get_clicks_by_affiliate(affiliate_id, limit=50)
    return jsonify(clicks)


@affiliate_bp.route('/api/source-stats')
@affiliate_required
def api_source_stats():
    """取得各來源點擊統計 API"""
    affiliate_id = session.get('affiliate_id')
    stats = get_clicks_by_source(affiliate_id)
    return jsonify(stats)
