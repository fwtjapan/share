from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from models import (
    get_affiliate_by_ref_code, get_affiliate_by_id, update_affiliate,
    get_orders_by_affiliate, get_payouts_by_affiliate, get_clicks_by_affiliate,
    get_affiliate_summary, get_clicks_by_source
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


def search_shopify_graphql(query, max_results=20):
    """使用 Shopify GraphQL API 搜尋商品"""
    shop_domain = Config.SHOPIFY_SHOP_DOMAIN
    access_token = Config.SHOPIFY_ACCESS_TOKEN
    
    if not shop_domain or not access_token:
        return []
    
    url = f"https://{shop_domain}/admin/api/2024-01/graphql.json"
    headers = {
        'X-Shopify-Access-Token': access_token,
        'Content-Type': 'application/json'
    }
    
    # GraphQL 查詢 - 使用 Shopify 內建搜尋
    graphql_query = """
    query searchProducts($query: String!) {
        products(first: 20, query: $query) {
            edges {
                node {
                    id
                    title
                    handle
                    vendor
                    status
                    variants(first: 1) {
                        edges {
                            node {
                                price
                            }
                        }
                    }
                    images(first: 1) {
                        edges {
                            node {
                                url
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
                'variables': {'query': query}
            },
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"GraphQL error: {response.status_code}")
            return []
        
        data = response.json()
        
        if 'errors' in data:
            print(f"GraphQL errors: {data['errors']}")
            return []
        
        products = []
        edges = data.get('data', {}).get('products', {}).get('edges', [])
        
        for edge in edges:
            node = edge.get('node', {})
            
            # 只顯示 active 商品
            if node.get('status') != 'ACTIVE':
                continue
            
            # 取得價格
            price = '0'
            variants = node.get('variants', {}).get('edges', [])
            if variants:
                price = variants[0].get('node', {}).get('price', '0')
            
            # 取得圖片
            image_url = ''
            images = node.get('images', {}).get('edges', [])
            if images:
                image_url = images[0].get('node', {}).get('url', '')
            
            products.append({
                'id': node.get('id', ''),
                'title': node.get('title', ''),
                'handle': node.get('handle', ''),
                'price': price,
                'image': image_url,
                'vendor': node.get('vendor', ''),
                'url': f"{Config.REDIRECT_TARGET}/products/{node.get('handle', '')}"
            })
        
        return products[:max_results]
        
    except Exception as e:
        print(f"Error searching products: {e}")
        return []


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
        update_data = {
            'email': request.form.get('email') or None,
            'social_facebook': request.form.get('social_facebook') or None,
            'social_instagram': request.form.get('social_instagram') or None,
            'social_threads': request.form.get('social_threads') or None,
            'social_youtube': request.form.get('social_youtube') or None,
            'social_tiktok': request.form.get('social_tiktok') or None
        }
        
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
    
    short_url = f"{Config.SHORT_URL_DOMAIN}/{affiliate['short_code']}"
    direct_url = f"{Config.REDIRECT_TARGET}?ref={affiliate['ref_code']}"
    
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
        # 使用 Shopify GraphQL 搜尋
        products = search_shopify_graphql(query, max_results=20)
        
        return jsonify({
            'products': products,
            'total_found': len(products),
            'shop_url': Config.REDIRECT_TARGET
        })
        
    except Exception as e:
        print(f"Error searching products: {e}")
        return jsonify({'products': [], 'error': '搜尋失敗'})


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
