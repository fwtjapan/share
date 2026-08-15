-- ============================================
-- GoyouLink 分潤系統 Database Schema
-- 在 Supabase SQL Editor 中執行此腳本
-- ============================================

-- 1. 代購業者（推廣者）表
CREATE TABLE affiliates (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name VARCHAR(255) NOT NULL,                    -- 代購業者名稱
    email VARCHAR(255) UNIQUE,                     -- Email
    domain VARCHAR(255),                           -- 他的 GoyouLink domain（如 erp.xxx.com）
    ref_code VARCHAR(50) UNIQUE NOT NULL,          -- 推薦碼（如 alice123）
    short_code VARCHAR(20) UNIQUE NOT NULL,        -- 短網址代碼（如 abc123）
    commission_rate DECIMAL(5,2) DEFAULT 5.00,     -- 佣金比例（預設 5%）
    status VARCHAR(20) DEFAULT 'active',           -- active / inactive
    total_clicks INTEGER DEFAULT 0,                -- 總點擊數
    total_orders INTEGER DEFAULT 0,                -- 總訂單數
    total_sales DECIMAL(12,2) DEFAULT 0,           -- 總銷售額
    total_commission DECIMAL(12,2) DEFAULT 0,      -- 總佣金
    pending_commission DECIMAL(12,2) DEFAULT 0,    -- 待發放佣金
    paid_commission DECIMAL(12,2) DEFAULT 0,       -- 已發放佣金
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. 點擊記錄表
CREATE TABLE clicks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    affiliate_id UUID REFERENCES affiliates(id) ON DELETE CASCADE,
    ip_address VARCHAR(45),                        -- 訪客 IP（可匿名化）
    user_agent TEXT,                               -- 瀏覽器資訊
    referer TEXT,                                  -- 來源頁面
    landed_url TEXT,                               -- 到達頁面
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. 推薦訂單表
CREATE TABLE referral_orders (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    affiliate_id UUID REFERENCES affiliates(id) ON DELETE CASCADE,
    shopify_order_id VARCHAR(100) UNIQUE NOT NULL, -- Shopify 訂單 ID
    order_number VARCHAR(50),                      -- 訂單顯示編號（#1001）
    order_total DECIMAL(12,2) NOT NULL,            -- 訂單金額
    currency VARCHAR(10) DEFAULT 'JPY',            -- 幣別
    commission_rate DECIMAL(5,2) NOT NULL,         -- 當時的佣金比例
    commission_amount DECIMAL(12,2) NOT NULL,      -- 應付佣金
    customer_email VARCHAR(255),                   -- 顧客 Email（可選）
    status VARCHAR(20) DEFAULT 'pending',          -- pending / confirmed / paid / refunded / cancelled
    order_created_at TIMESTAMP WITH TIME ZONE,     -- Shopify 訂單建立時間
    confirmed_at TIMESTAMP WITH TIME ZONE,         -- 確認時間（出貨後）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. 佣金發放記錄表
CREATE TABLE payouts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    affiliate_id UUID REFERENCES affiliates(id) ON DELETE CASCADE,
    amount DECIMAL(12,2) NOT NULL,                 -- 發放金額
    currency VARCHAR(10) DEFAULT 'JPY',            -- 幣別
    payment_method VARCHAR(50),                    -- 付款方式
    payment_details TEXT,                          -- 付款詳情（如銀行帳號後四碼）
    note TEXT,                                     -- 備註
    status VARCHAR(20) DEFAULT 'completed',        -- pending / completed / failed
    paid_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. 系統設定表（可選，用於存放全域設定）
CREATE TABLE settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初始化預設設定
INSERT INTO settings (key, value) VALUES 
    ('default_commission_rate', '5'),
    ('cookie_days', '30'),
    ('min_payout_jpy', '20000');

-- ============================================
-- 索引（提升查詢效能）
-- ============================================

CREATE INDEX idx_affiliates_ref_code ON affiliates(ref_code);
CREATE INDEX idx_affiliates_short_code ON affiliates(short_code);
CREATE INDEX idx_affiliates_status ON affiliates(status);
CREATE INDEX idx_clicks_affiliate_id ON clicks(affiliate_id);
CREATE INDEX idx_clicks_created_at ON clicks(created_at);
CREATE INDEX idx_referral_orders_affiliate_id ON referral_orders(affiliate_id);
CREATE INDEX idx_referral_orders_status ON referral_orders(status);
CREATE INDEX idx_referral_orders_shopify_order_id ON referral_orders(shopify_order_id);
CREATE INDEX idx_payouts_affiliate_id ON payouts(affiliate_id);

-- ============================================
-- 自動更新 updated_at 的觸發器
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_affiliates_updated_at
    BEFORE UPDATE ON affiliates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_referral_orders_updated_at
    BEFORE UPDATE ON referral_orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Row Level Security (RLS) - 可選
-- 如果需要讓代購業者只能看到自己的資料
-- ============================================

-- ALTER TABLE affiliates ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE clicks ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE referral_orders ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE payouts ENABLE ROW LEVEL SECURITY;

-- ============================================
-- 完成！
-- ============================================
