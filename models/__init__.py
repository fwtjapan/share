from supabase import create_client, Client
from config import Config
import shortuuid
from datetime import datetime, timezone

# 初始化 Supabase client
supabase: Client = None

def init_supabase():
    global supabase
    if Config.SUPABASE_URL and Config.SUPABASE_KEY:
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return supabase

def get_supabase():
    global supabase
    if supabase is None:
        init_supabase()
    return supabase


# ============================================
# Affiliate（代購業者）操作
# ============================================

def create_affiliate(name: str, email: str = None, domain: str = None, 
                     ref_code: str = None, commission_rate: float = None,
                     affiliate_type: str = 'affiliate',
                     social_facebook: str = None, social_instagram: str = None,
                     social_threads: str = None, social_youtube: str = None,
                     social_tiktok: str = None):
    """建立新的代購業者"""
    db = get_supabase()
    
    # 自動產生 ref_code 如果沒提供
    if not ref_code:
        ref_code = shortuuid.uuid()[:8].lower()
    
    # 產生短網址代碼
    short_code = shortuuid.uuid()[:6].lower()
    
    # 使用預設佣金比例
    if commission_rate is None:
        commission_rate = Config.DEFAULT_COMMISSION_RATE
    
    data = {
        'name': name,
        'email': email,
        'domain': domain,
        'ref_code': ref_code,
        'short_code': short_code,
        'commission_rate': commission_rate,
        'status': 'active',
        'type': affiliate_type,
        'social_facebook': social_facebook,
        'social_instagram': social_instagram,
        'social_threads': social_threads,
        'social_youtube': social_youtube,
        'social_tiktok': social_tiktok
    }
    
    try:
        result = db.table('affiliates').insert(data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in create_affiliate: {e}")
        return None


def get_affiliate_by_id(affiliate_id: str):
    """用 ID 取得代購業者"""
    db = get_supabase()
    try:
        result = db.table('affiliates').select('*').eq('id', affiliate_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_affiliate_by_id: {e}")
        return None


def get_affiliate_by_ref_code(ref_code: str):
    """用推薦碼取得代購業者"""
    db = get_supabase()
    try:
        result = db.table('affiliates').select('*').eq('ref_code', ref_code).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_affiliate_by_ref_code: {e}")
        return None


def get_affiliate_by_short_code(short_code: str):
    """用短網址代碼取得代購業者"""
    db = get_supabase()
    try:
        result = db.table('affiliates').select('*').eq('short_code', short_code).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_affiliate_by_short_code: {e}")
        return None


def get_all_affiliates(status: str = None, affiliate_type: str = None):
    """取得所有代購業者"""
    db = get_supabase()
    try:
        query = db.table('affiliates').select('*')
        if status:
            query = query.eq('status', status)
        if affiliate_type:
            query = query.eq('type', affiliate_type)
        result = query.order('created_at', desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error in get_all_affiliates: {e}")
        return []


def update_affiliate(affiliate_id: str, **kwargs):
    """更新代購業者資料"""
    db = get_supabase()
    try:
        result = db.table('affiliates').update(kwargs).eq('id', affiliate_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in update_affiliate: {e}")
        return None


def update_affiliate_stats(affiliate_id: str, clicks: int = 0, orders: int = 0, 
                           sales: float = 0, commission: float = 0):
    """更新代購業者統計數據"""
    db = get_supabase()
    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None
    
    update_data = {
        'total_clicks': (affiliate.get('total_clicks') or 0) + clicks,
        'total_orders': (affiliate.get('total_orders') or 0) + orders,
        'total_sales': float(affiliate.get('total_sales') or 0) + sales,
        'total_commission': float(affiliate.get('total_commission') or 0) + commission,
        'pending_commission': float(affiliate.get('pending_commission') or 0) + commission
    }
    
    return update_affiliate(affiliate_id, **update_data)


# ============================================
# Click（點擊）操作
# ============================================

def record_click(affiliate_id: str, ip_address: str = None, 
                 user_agent: str = None, referer: str = None, 
                 landed_url: str = None, source: str = None):
    """記錄一次點擊"""
    db = get_supabase()
    
    data = {
        'affiliate_id': affiliate_id,
        'ip_address': ip_address,
        'user_agent': user_agent,
        'referer': referer,
        'landed_url': landed_url,
        'source': source  # 新增來源欄位
    }
    
    try:
        result = db.table('clicks').insert(data).execute()
        
        # 更新 affiliate 的點擊數
        if result.data:
            update_affiliate_stats(affiliate_id, clicks=1)
        
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in record_click: {e}")
        return None


def get_clicks_by_affiliate(affiliate_id: str, limit: int = 100):
    """取得代購業者的點擊記錄"""
    db = get_supabase()
    try:
        result = db.table('clicks').select('*').eq('affiliate_id', affiliate_id)\
            .order('created_at', desc=True).limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error in get_clicks_by_affiliate: {e}")
        return []


def get_clicks_by_source(affiliate_id: str):
    """取得代購業者各來源的點擊統計"""
    db = get_supabase()
    try:
        # 取得所有點擊記錄
        result = db.table('clicks').select('source').eq('affiliate_id', affiliate_id).execute()
        
        if not result.data:
            return {}
        
        # 手動計算各來源的數量
        source_counts = {}
        for click in result.data:
            source = click.get('source') or 'direct'
            source_counts[source] = source_counts.get(source, 0) + 1
        
        return source_counts
    except Exception as e:
        print(f"Error in get_clicks_by_source: {e}")
        return {}


# ============================================
# Referral Order（推薦訂單）操作
# ============================================

def create_referral_order(affiliate_id: str, shopify_order_id: str, order_number: str,
                          order_total: float, currency: str = 'JPY', 
                          customer_email: str = None, order_created_at: str = None):
    """建立推薦訂單記錄"""
    db = get_supabase()
    
    # 取得代購業者的佣金比例
    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None
    
    commission_rate = float(affiliate.get('commission_rate') or 5)
    commission_amount = round(order_total * commission_rate / 100, 2)
    
    data = {
        'affiliate_id': affiliate_id,
        'shopify_order_id': shopify_order_id,
        'order_number': order_number,
        'order_total': order_total,
        'currency': currency,
        'commission_rate': commission_rate,
        'commission_amount': commission_amount,
        'customer_email': customer_email,
        'order_created_at': order_created_at,
        'status': 'pending'
    }
    
    try:
        result = db.table('referral_orders').insert(data).execute()
        
        # 更新 affiliate 統計（但佣金先不算，等出貨確認後再算）
        if result.data:
            update_affiliate_stats(affiliate_id, orders=1, sales=order_total)
        
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in create_referral_order: {e}")
        return None


def get_order_by_shopify_id(shopify_order_id: str):
    """用 Shopify 訂單 ID 取得推薦訂單"""
    db = get_supabase()
    try:
        result = db.table('referral_orders').select('*').eq('shopify_order_id', shopify_order_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_order_by_shopify_id: {e}")
        return None


def get_orders_by_affiliate(affiliate_id: str, status: str = None, limit: int = 100):
    """取得代購業者的推薦訂單"""
    db = get_supabase()
    try:
        query = db.table('referral_orders').select('*').eq('affiliate_id', affiliate_id)
        if status:
            query = query.eq('status', status)
        result = query.order('created_at', desc=True).limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error in get_orders_by_affiliate: {e}")
        return []


def get_all_orders(status: str = None, limit: int = 100):
    """取得所有推薦訂單"""
    db = get_supabase()
    try:
        # 簡化查詢，不用 join
        query = db.table('referral_orders').select('*')
        if status:
            query = query.eq('status', status)
        result = query.order('created_at', desc=True).limit(limit).execute()
        
        orders = result.data if result.data else []
        
        # 手動補上 affiliate 資訊
        for order in orders:
            if order.get('affiliate_id'):
                affiliate = get_affiliate_by_id(order['affiliate_id'])
                order['affiliates'] = affiliate
        
        return orders
    except Exception as e:
        print(f"Error in get_all_orders: {e}")
        return []


def update_order_status(order_id: str, status: str):
    """更新訂單狀態"""
    db = get_supabase()
    
    try:
        update_data = {'status': status}
        
        # 如果是確認（出貨），記錄確認時間並更新佣金
        if status == 'confirmed':
            update_data['confirmed_at'] = datetime.now(timezone.utc).isoformat()
            
            # 取得訂單資訊
            order = db.table('referral_orders').select('*').eq('id', order_id).execute()
            if order.data:
                order = order.data[0]
                # 更新 affiliate 的待發放佣金
                affiliate = get_affiliate_by_id(order['affiliate_id'])
                if affiliate:
                    new_pending = float(affiliate.get('pending_commission') or 0) + float(order['commission_amount'])
                    update_affiliate(order['affiliate_id'], pending_commission=new_pending)
        
        # 如果是退款，扣回佣金
        elif status == 'refunded':
            order = db.table('referral_orders').select('*').eq('id', order_id).execute()
            if order.data:
                order = order.data[0]
                if order['status'] == 'confirmed':
                    # 已確認的訂單退款，要扣回佣金
                    affiliate = get_affiliate_by_id(order['affiliate_id'])
                    if affiliate:
                        new_pending = max(0, float(affiliate.get('pending_commission') or 0) - float(order['commission_amount']))
                        update_affiliate(order['affiliate_id'], pending_commission=new_pending)
        
        result = db.table('referral_orders').update(update_data).eq('id', order_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in update_order_status: {e}")
        return None


# ============================================
# Payout（佣金發放）操作
# ============================================

def create_payout(affiliate_id: str, amount: float, currency: str = 'JPY',
                  payment_method: str = None, payment_details: str = None, note: str = None):
    """建立佣金發放記錄"""
    db = get_supabase()
    
    data = {
        'affiliate_id': affiliate_id,
        'amount': amount,
        'currency': currency,
        'payment_method': payment_method,
        'payment_details': payment_details,
        'note': note,
        'status': 'completed'
    }
    
    try:
        result = db.table('payouts').insert(data).execute()
        
        # 更新 affiliate 的佣金狀態
        if result.data:
            affiliate = get_affiliate_by_id(affiliate_id)
            if affiliate:
                new_pending = max(0, float(affiliate.get('pending_commission') or 0) - amount)
                new_paid = float(affiliate.get('paid_commission') or 0) + amount
                update_affiliate(affiliate_id, pending_commission=new_pending, paid_commission=new_paid)
        
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in create_payout: {e}")
        return None


def get_payouts_by_affiliate(affiliate_id: str, limit: int = 100):
    """取得代購業者的發放記錄"""
    db = get_supabase()
    try:
        result = db.table('payouts').select('*').eq('affiliate_id', affiliate_id)\
            .order('paid_at', desc=True).limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"Error in get_payouts_by_affiliate: {e}")
        return []


def get_all_payouts(limit: int = 100):
    """取得所有發放記錄"""
    db = get_supabase()
    try:
        result = db.table('payouts').select('*').order('paid_at', desc=True).limit(limit).execute()
        
        payouts = result.data if result.data else []
        
        # 手動補上 affiliate 資訊
        for payout in payouts:
            if payout.get('affiliate_id'):
                affiliate = get_affiliate_by_id(payout['affiliate_id'])
                payout['affiliates'] = affiliate
        
        return payouts
    except Exception as e:
        print(f"Error in get_all_payouts: {e}")
        return []


# ============================================
# 統計查詢
# ============================================

def get_affiliate_summary(affiliate_id: str):
    """取得代購業者的完整統計摘要"""
    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None
    
    db = get_supabase()
    
    try:
        pending_orders = db.table('referral_orders').select('id', count='exact')\
            .eq('affiliate_id', affiliate_id).eq('status', 'pending').execute()
        
        confirmed_orders = db.table('referral_orders').select('id', count='exact')\
            .eq('affiliate_id', affiliate_id).eq('status', 'confirmed').execute()
        
        # 取得各來源點擊統計
        source_stats = get_clicks_by_source(affiliate_id)
        
        return {
            'affiliate': affiliate,
            'pending_orders_count': pending_orders.count if pending_orders else 0,
            'confirmed_orders_count': confirmed_orders.count if confirmed_orders else 0,
            'short_url': f"{Config.SHORT_URL_DOMAIN}/{affiliate['short_code']}",
            'source_stats': source_stats
        }
    except Exception as e:
        print(f"Error in get_affiliate_summary: {e}")
        return {
            'affiliate': affiliate,
            'pending_orders_count': 0,
            'confirmed_orders_count': 0,
            'short_url': f"{Config.SHORT_URL_DOMAIN}/{affiliate.get('short_code', '')}",
            'source_stats': {}
        }


def get_dashboard_stats():
    """取得管理後台儀表板統計"""
    db = get_supabase()
    
    try:
        # 總代購業者數
        affiliates = db.table('affiliates').select('id', count='exact').eq('status', 'active').execute()
        
        # 總訂單數
        orders = db.table('referral_orders').select('id', count='exact').execute()
        
        # 待處理訂單
        pending = db.table('referral_orders').select('id', count='exact').eq('status', 'pending').execute()
        
        # 總銷售額和佣金
        all_affiliates = db.table('affiliates').select('total_sales, total_commission, pending_commission').execute()
        
        total_sales = sum(float(a.get('total_sales') or 0) for a in all_affiliates.data) if all_affiliates.data else 0
        total_commission = sum(float(a.get('total_commission') or 0) for a in all_affiliates.data) if all_affiliates.data else 0
        pending_commission = sum(float(a.get('pending_commission') or 0) for a in all_affiliates.data) if all_affiliates.data else 0
        
        return {
            'total_affiliates': affiliates.count if affiliates else 0,
            'total_orders': orders.count if orders else 0,
            'pending_orders': pending.count if pending else 0,
            'total_sales': total_sales,
            'total_commission': total_commission,
            'pending_commission': pending_commission
        }
    except Exception as e:
        print(f"Error in get_dashboard_stats: {e}")
        return {
            'total_affiliates': 0,
            'total_orders': 0,
            'pending_orders': 0,
            'total_sales': 0,
            'total_commission': 0,
            'pending_commission': 0
        }
