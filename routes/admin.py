from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from models import (
    get_all_affiliates, get_affiliate_by_id, create_affiliate, update_affiliate,
    get_all_orders, update_order_status,
    get_all_payouts, create_payout,
    get_dashboard_stats, get_affiliate_summary
)
from config import Config

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """管理員登入驗證裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================
# 登入/登出
# ============================================

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """管理員登入頁面"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        else:
            return render_template('admin/login.html', error='帳號或密碼錯誤')
    
    return render_template('admin/login.html')


@admin_bp.route('/logout')
def logout():
    """登出"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))


# ============================================
# 儀表板
# ============================================

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """管理後台儀表板"""
    stats = get_dashboard_stats()
    recent_orders = get_all_orders(limit=10)
    return render_template('admin/dashboard.html', stats=stats, recent_orders=recent_orders)


# ============================================
# 代購業者管理
# ============================================

@admin_bp.route('/affiliates')
@admin_required
def affiliates_list():
    """代購業者列表"""
    type_filter = request.args.get('type')
    affiliates = get_all_affiliates(affiliate_type=type_filter)
    return render_template('admin/affiliates.html', affiliates=affiliates, config=Config, type_filter=type_filter)


@admin_bp.route('/affiliates/create', methods=['GET', 'POST'])
@admin_required
def affiliates_create():
    """新增代購業者"""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        domain = request.form.get('domain')
        ref_code = request.form.get('ref_code') or None
        commission_rate = request.form.get('commission_rate')
        affiliate_type = request.form.get('type', 'affiliate')
        
        # 社群媒體
        social_facebook = request.form.get('social_facebook') or None
        social_instagram = request.form.get('social_instagram') or None
        social_threads = request.form.get('social_threads') or None
        social_youtube = request.form.get('social_youtube') or None
        social_tiktok = request.form.get('social_tiktok') or None
        
        if commission_rate:
            commission_rate = float(commission_rate)
        else:
            commission_rate = None
        
        affiliate = create_affiliate(
            name=name,
            email=email,
            domain=domain,
            ref_code=ref_code,
            commission_rate=commission_rate,
            affiliate_type=affiliate_type,
            social_facebook=social_facebook,
            social_instagram=social_instagram,
            social_threads=social_threads,
            social_youtube=social_youtube,
            social_tiktok=social_tiktok
        )
        
        if affiliate:
            return redirect(url_for('admin.affiliates_list'))
        else:
            return render_template('admin/affiliate_form.html', error='建立失敗', config=Config)
    
    return render_template('admin/affiliate_form.html', config=Config)


@admin_bp.route('/affiliates/<affiliate_id>')
@admin_required
def affiliates_detail(affiliate_id):
    """代購業者詳情"""
    summary = get_affiliate_summary(affiliate_id)
    if not summary:
        return redirect(url_for('admin.affiliates_list'))
    
    from models import get_orders_by_affiliate, get_payouts_by_affiliate
    orders = get_orders_by_affiliate(affiliate_id, limit=50)
    payouts = get_payouts_by_affiliate(affiliate_id, limit=20)
    
    return render_template('admin/affiliate_detail.html', 
                           summary=summary, orders=orders, payouts=payouts, config=Config)


@admin_bp.route('/affiliates/<affiliate_id>/edit', methods=['GET', 'POST'])
@admin_required
def affiliates_edit(affiliate_id):
    """編輯代購業者"""
    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return redirect(url_for('admin.affiliates_list'))
    
    if request.method == 'POST':
        update_data = {
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'domain': request.form.get('domain'),
            'commission_rate': float(request.form.get('commission_rate', 5)),
            'status': request.form.get('status', 'active'),
            'type': request.form.get('type', 'affiliate'),
            # 社群媒體
            'social_facebook': request.form.get('social_facebook') or None,
            'social_instagram': request.form.get('social_instagram') or None,
            'social_threads': request.form.get('social_threads') or None,
            'social_youtube': request.form.get('social_youtube') or None,
            'social_tiktok': request.form.get('social_tiktok') or None
        }
        
        update_affiliate(affiliate_id, **update_data)
        return redirect(url_for('admin.affiliates_detail', affiliate_id=affiliate_id))
    
    return render_template('admin/affiliate_form.html', affiliate=affiliate, config=Config)


# ============================================
# 訂單管理
# ============================================

@admin_bp.route('/orders')
@admin_required
def orders_list():
    """訂單列表"""
    status_filter = request.args.get('status')
    orders = get_all_orders(status=status_filter, limit=100)
    return render_template('admin/orders.html', orders=orders, status_filter=status_filter)


@admin_bp.route('/orders/<order_id>/status', methods=['POST'])
@admin_required
def orders_update_status(order_id):
    """更新訂單狀態"""
    new_status = request.form.get('status')
    if new_status in ['pending', 'confirmed', 'paid', 'refunded', 'cancelled']:
        update_order_status(order_id, new_status)
    
    return redirect(request.referrer or url_for('admin.orders_list'))


# ============================================
# 佣金發放
# ============================================

@admin_bp.route('/payouts')
@admin_required
def payouts_list():
    """發放記錄列表"""
    payouts = get_all_payouts(limit=100)
    return render_template('admin/payouts.html', payouts=payouts)


@admin_bp.route('/payouts/create', methods=['GET', 'POST'])
@admin_required
def payouts_create():
    """建立發放記錄"""
    if request.method == 'POST':
        affiliate_id = request.form.get('affiliate_id')
        amount = float(request.form.get('amount', 0))
        payment_method = request.form.get('payment_method')
        payment_details = request.form.get('payment_details')
        note = request.form.get('note')
        
        if affiliate_id and amount > 0:
            payout = create_payout(
                affiliate_id=affiliate_id,
                amount=amount,
                payment_method=payment_method,
                payment_details=payment_details,
                note=note
            )
            
            if payout:
                return redirect(url_for('admin.payouts_list'))
    
    affiliates = get_all_affiliates(status='active')
    return render_template('admin/payout_form.html', affiliates=affiliates, config=Config)


# ============================================
# API endpoints（給前端 AJAX 用）
# ============================================

@admin_bp.route('/api/stats')
@admin_required
def api_stats():
    """取得統計數據 API"""
    stats = get_dashboard_stats()
    return jsonify(stats)


@admin_bp.route('/api/affiliates')
@admin_required
def api_affiliates():
    """取得代購業者列表 API"""
    affiliates = get_all_affiliates()
    return jsonify(affiliates)


@admin_bp.route('/api/affiliates/<affiliate_id>')
@admin_required
def api_affiliate_detail(affiliate_id):
    """取得代購業者詳情 API"""
    summary = get_affiliate_summary(affiliate_id)
    return jsonify(summary)
