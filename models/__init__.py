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
    else:
        print("[FATAL] SUPABASE_URL / SUPABASE_KEY 未設定，所有資料庫操作都會失敗。"
              " 短網址將不會記錄點擊，後台會看不到任何資料。")
    return supabase


def get_supabase():
    global supabase
    if supabase is None:
        init_supabase()
    return supabase


def _money(value):
    """
    金額正規化。

    修正：日圓沒有輔幣單位，但原本佣金用 round(..., 2) 存成兩位小數，
    畫面又一律以整數顯示。¥3,333 的 5% 會存成 166.65 但顯示成 ¥167，
    管理員照著發放 167 就會產生 -0.35 的差額被靜默吃掉，
    大量訂單後會累積成無法對帳的落差。現在一律用整數日圓。
    """
    try:
        return int(round(float(value or 0)))
    except (ValueError, TypeError):
        return 0


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

    if not ref_code:
        ref_code = shortuuid.uuid()[:8].lower()

    short_code = shortuuid.uuid()[:6].lower()

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
    """
    更新代購業者統計數據（可正可負，負數代表回沖）。

    修正（嚴重）：原本不論這次要改什麼，都會把 total_clicks / total_orders /
    total_sales / total_commission / pending_commission 五個欄位「整列寫回去」。
    這是典型的 read-modify-write，沒有任何原子性保護。

    實際會發生的災情：業者待發放 ¥20,000，管理員按下發放（寫入 待發放=0,
    已發放=20000）的同一秒剛好有人點了短網址，那個請求在發放之前就讀到
    舊快照（待發放=20000），隨後把 待發放=20000 寫回去。結果變成
    「已發放 ¥20,000 且待發放 ¥20,000」，同一筆佣金被領兩次。
    而點擊是全站最高頻的寫入路徑，碰撞機率不低。

    現在改成：只寫本次真正變動的欄位，把互相覆蓋的範圍降到最小。
    （更根本的解法是改用 Postgres 的原子累加 RPC，見檔案末尾註解。）
    """
    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None

    update_data = {}
    if clicks:
        update_data['total_clicks'] = max(0, int(affiliate.get('total_clicks') or 0) + clicks)
    if orders:
        update_data['total_orders'] = max(0, int(affiliate.get('total_orders') or 0) + orders)
    if sales:
        update_data['total_sales'] = max(0, _money(affiliate.get('total_sales')) + _money(sales))
    if commission:
        update_data['total_commission'] = max(
            0, _money(affiliate.get('total_commission')) + _money(commission))
        update_data['pending_commission'] = max(
            0, _money(affiliate.get('pending_commission')) + _money(commission))

    if not update_data:
        return affiliate

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
        'source': source
    }

    try:
        result = db.table('clicks').insert(data).execute()

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
        result = db.table('clicks').select('source').eq('affiliate_id', affiliate_id).execute()

        if not result.data:
            return {}

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

    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None

    # 修正：原本寫 float(affiliate.get('commission_rate') or 5)。
    # 0 在 Python 是 falsy，所以 `0 or 5` 會得到 5 —— 把佣金設成 0% 的業者
    # 仍然會被算 5% 佣金。（對照 create_affiliate 用的是正確的 `is None` 判斷。）
    rate = affiliate.get('commission_rate')
    commission_rate = float(rate) if rate is not None else float(Config.DEFAULT_COMMISSION_RATE)

    order_total = _money(order_total)
    commission_amount = _money(order_total * commission_rate / 100)

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

        # 訂單成立時只累加訂單數與銷售額，佣金要等出貨確認後才算
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
        result = db.table('referral_orders').select('*')\
            .eq('shopify_order_id', shopify_order_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_order_by_shopify_id: {e}")
        return None


def get_order_by_id(order_id: str):
    """用內部 ID 取得推薦訂單"""
    db = get_supabase()
    try:
        result = db.table('referral_orders').select('*').eq('id', order_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Error in get_order_by_id: {e}")
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
        query = db.table('referral_orders').select('*')
        if status:
            query = query.eq('status', status)
        result = query.order('created_at', desc=True).limit(limit).execute()

        orders = result.data if result.data else []

        # 手動補上 affiliate 資訊（用快取避免 N+1 重複查詢同一個業者）
        cache = {}
        for order in orders:
            aid = order.get('affiliate_id')
            if aid:
                if aid not in cache:
                    cache[aid] = get_affiliate_by_id(aid)
                order['affiliates'] = cache[aid]

        return orders
    except Exception as e:
        print(f"Error in get_all_orders: {e}")
        return []


# 合法的狀態轉移。修正：原本完全沒有狀態機檢查，任何狀態都能改成任何狀態。
_ALLOWED_TRANSITIONS = {
    'pending': {'confirmed', 'cancelled', 'refunded'},
    'confirmed': {'refunded', 'cancelled', 'paid'},
    'paid': {'refunded'},
    'refunded': set(),
    'cancelled': set(),
}


def update_order_status(order_id: str, status: str):
    """
    更新訂單狀態，並同步調整業者的佣金與統計。

    修正了以下幾個嚴重問題：

    1.（重複計算）原本沒有檢查訂單目前狀態就直接加佣金。webhook 那條路徑有
       `status == 'pending'` 護欄，但後台的 POST 端點完全沒有 —— 管理員連點
       兩下「確認」按鈕、瀏覽器重送表單、或直接 curl，佣金就會加兩次。
       ¥10,000 訂單 5% 連點兩次就變成付 10%。現在改用狀態機檢查。

    2.（總佣金永遠是 0）原本 confirmed 分支只更新 pending_commission，
       從頭到尾沒有任何一行寫入 total_commission，導致管理後台和業者頁面
       四個「總佣金」欄位永遠顯示 ¥0。現在兩個欄位一起累加。

    3.（取消不回沖）原本只有 confirmed / refunded 兩個分支，沒有 cancelled。
       已確認的訂單被取消時佣金一毛都不退，管理員會照著錯誤的待發放金額匯款。

    4.（訂單數與銷售額只加不減）退款和取消都不回沖 total_orders / total_sales，
       導致儀表板的總銷售額永久灌水。現在會一併回沖。

    5.（paid 狀態的退款漏洞）原本退款只檢查 `status == 'confirmed'`，
       若訂單已被標記為 paid，退款時佣金完全不扣回。現在一併處理。
    """
    db = get_supabase()

    try:
        order = get_order_by_id(order_id)
        if not order:
            print(f"[WARN] update_order_status: 找不到訂單 {order_id}")
            return None

        current = order.get('status') or 'pending'

        if current == status:
            # 冪等：已經是這個狀態就什麼都不做，直接回傳現況
            return order

        if status not in _ALLOWED_TRANSITIONS.get(current, set()):
            print(f"[WARN] 不合法的狀態轉移：{current} -> {status}（訂單 {order_id}），已忽略")
            return order

        affiliate_id = order.get('affiliate_id')
        commission = _money(order.get('commission_amount'))
        order_total = _money(order.get('order_total'))

        update_data = {'status': status}

        # 先更新訂單本身，成功之後才動業者的錢。
        # 修正：原本順序相反（先加佣金再更新訂單），若更新訂單那步失敗，
        # 例外會被 except 吞掉，但佣金已經加上去了 —— 訂單仍顯示「待確認」，
        # 管理員之後手動確認會再加一次。
        if status == 'confirmed':
            update_data['confirmed_at'] = datetime.now(timezone.utc).isoformat()

        result = db.table('referral_orders').update(update_data).eq('id', order_id).execute()
        if not result.data:
            print(f"[ERROR] 訂單 {order_id} 狀態更新失敗，未調整佣金")
            return None

        # 訂單更新成功，接著調整業者統計
        if affiliate_id:
            if status == 'confirmed':
                # 出貨確認：佣金正式計入總佣金與待發放
                update_affiliate_stats(affiliate_id, commission=commission)

            elif status in ('refunded', 'cancelled'):
                # 回沖訂單數與銷售額
                update_affiliate_stats(affiliate_id, orders=-1, sales=-order_total)
                # 若佣金當初已經計入（confirmed 或 paid），要扣回來
                if current in ('confirmed', 'paid'):
                    update_affiliate_stats(affiliate_id, commission=-commission)

        return result.data[0]

    except Exception as e:
        print(f"Error in update_order_status: {e}")
        return None


def apply_refund(order_id: str, refund_amount: float, order_total: float):
    """
    依實際退款金額按比例回沖佣金。

    修正：原本任何金額的退款都把整筆訂單標記為 refunded 並扣全額佣金。
    Shopify 的 refunds/create 對部分退款同樣會觸發，所以 ¥10,000 訂單
    只退 ¥300 運費時，佣金會整整扣掉全額（正確應只扣 ¥15）。
    """
    order = get_order_by_id(order_id)
    if not order:
        return None

    refund_amount = _money(refund_amount)
    order_total = _money(order_total) or _money(order.get('order_total'))

    if order_total <= 0:
        return None

    fully_refunded = refund_amount >= order_total

    if fully_refunded:
        update_order_status(order_id, 'refunded')
        return {'fully_refunded': True}

    # 部分退款：只按比例扣佣金，訂單狀態維持不變
    current = order.get('status') or 'pending'
    if current in ('confirmed', 'paid') and order.get('affiliate_id'):
        commission = _money(order.get('commission_amount'))
        portion = _money(commission * refund_amount / order_total)
        update_affiliate_stats(order['affiliate_id'], commission=-portion,
                               sales=-refund_amount)
        print(f"[REFUND] 訂單 {order_id} 部分退款 {refund_amount}，回沖佣金 {portion}")

    return {'fully_refunded': False}


# ============================================
# Payout（佣金發放）操作
# ============================================

def create_payout(affiliate_id: str, amount: float, currency: str = 'JPY',
                  payment_method: str = None, payment_details: str = None, note: str = None):
    """
    建立佣金發放記錄。

    修正：原本完全沒有伺服器端驗證，金額上限只靠前端 JS 擋，直接 POST 就能繞過。
    業者待發放 ¥500 時送出 amount=999999，會變成待發放 0、已發放 ¥999,999，
    而且沒有任何錯誤訊息。現在改成：金額必須是正數、不得超過待發放餘額。

    回傳 (payout, error_message) 讓呼叫端能把錯誤顯示給使用者。
    """
    db = get_supabase()

    amount = _money(amount)
    if amount <= 0:
        return None, '發放金額必須大於 0'

    affiliate = get_affiliate_by_id(affiliate_id)
    if not affiliate:
        return None, '找不到該代購業者'

    pending = _money(affiliate.get('pending_commission'))
    if amount > pending:
        return None, f'發放金額 ¥{amount:,} 超過待發放餘額 ¥{pending:,}'

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

        if result.data:
            # 重新讀一次，減少與其他寫入互相覆蓋的窗口
            latest = get_affiliate_by_id(affiliate_id)
            if latest:
                new_pending = max(0, _money(latest.get('pending_commission')) - amount)
                new_paid = _money(latest.get('paid_commission')) + amount
                update_affiliate(affiliate_id,
                                 pending_commission=new_pending,
                                 paid_commission=new_paid)

            # 把這次結清的訂單標記為 paid，避免同一批佣金被重複發放
            _mark_orders_paid(affiliate_id, amount)

        return (result.data[0] if result.data else None), None
    except Exception as e:
        print(f"Error in create_payout: {e}")
        return None, f'建立發放記錄失敗：{e}'


def _mark_orders_paid(affiliate_id: str, amount: int):
    """
    依發放金額，由舊到新把已確認訂單標記為 paid。

    修正：原本發放後訂單永遠停在 confirmed，沒有任何欄位能區分
    「已結清 / 未結清」，導致同一批訂單可以被重複發放，
    退款時也無從得知這筆佣金早就被扣過一次。
    """
    db = get_supabase()
    try:
        result = db.table('referral_orders').select('*')\
            .eq('affiliate_id', affiliate_id).eq('status', 'confirmed')\
            .order('created_at', desc=False).execute()

        remaining = amount
        for order in (result.data or []):
            if remaining <= 0:
                break
            c = _money(order.get('commission_amount'))
            if c <= remaining:
                db.table('referral_orders').update({'status': 'paid'})\
                    .eq('id', order['id']).execute()
                remaining -= c
    except Exception as e:
        print(f"Error in _mark_orders_paid: {e}")


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

        cache = {}
        for payout in payouts:
            aid = payout.get('affiliate_id')
            if aid:
                if aid not in cache:
                    cache[aid] = get_affiliate_by_id(aid)
                payout['affiliates'] = cache[aid]

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

        source_stats = get_clicks_by_source(affiliate_id)

        return {
            'affiliate': affiliate,
            'pending_orders_count': pending_orders.count if pending_orders else 0,
            'confirmed_orders_count': confirmed_orders.count if confirmed_orders else 0,
            'short_url': f"{Config.SHORT_URL_DOMAIN}/{affiliate.get('short_code', '')}",
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
        affiliates = db.table('affiliates').select('id', count='exact')\
            .eq('status', 'active').execute()

        orders = db.table('referral_orders').select('id', count='exact').execute()

        pending = db.table('referral_orders').select('id', count='exact')\
            .eq('status', 'pending').execute()

        all_affiliates = db.table('affiliates')\
            .select('total_sales, total_commission, pending_commission').execute()

        rows = all_affiliates.data or []
        total_sales = sum(_money(a.get('total_sales')) for a in rows)
        total_commission = sum(_money(a.get('total_commission')) for a in rows)
        pending_commission = sum(_money(a.get('pending_commission')) for a in rows)

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


# ============================================
# 進階：原子累加（建議日後改用）
# ============================================
# 目前 update_affiliate_stats() 仍是「先讀再寫」，雖然已縮小到只寫變動欄位，
# 高併發下理論上仍可能互相覆蓋。若要徹底解決，可在 Supabase SQL Editor
# 建立以下函式，然後改用 db.rpc('increment_affiliate_stats', {...})：
#
# CREATE OR REPLACE FUNCTION increment_affiliate_stats(
#     p_affiliate_id UUID,
#     p_clicks INT DEFAULT 0,
#     p_orders INT DEFAULT 0,
#     p_sales NUMERIC DEFAULT 0,
#     p_commission NUMERIC DEFAULT 0
# ) RETURNS VOID AS $$
# BEGIN
#     UPDATE affiliates SET
#         total_clicks       = GREATEST(0, COALESCE(total_clicks, 0) + p_clicks),
#         total_orders       = GREATEST(0, COALESCE(total_orders, 0) + p_orders),
#         total_sales        = GREATEST(0, COALESCE(total_sales, 0) + p_sales),
#         total_commission   = GREATEST(0, COALESCE(total_commission, 0) + p_commission),
#         pending_commission = GREATEST(0, COALESCE(pending_commission, 0) + p_commission)
#     WHERE id = p_affiliate_id;
# END;
# $$ LANGUAGE plpgsql;
