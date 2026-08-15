# GoyouLink 分潤系統

一個用於追蹤推薦銷售和計算佣金的分潤系統，整合 Shopify 電商平台。

## 功能特色

- 🔗 **短網址服務**：為每個代購業者產生專屬短網址
- 📊 **訂單追蹤**：透過 Shopify Webhook 自動追蹤推薦訂單
- 💰 **佣金計算**：自動計算佣金，支援個別設定比例
- 📱 **代購業者入口**：讓代購業者查詢自己的推薦成效
- 🛡️ **管理後台**：完整的訂單和佣金管理功能

## 技術架構

- **後端**：Python Flask
- **資料庫**：Supabase (PostgreSQL)
- **部署**：Zeabur

## 快速開始

### 1. 設定 Supabase

1. 前往 [Supabase](https://supabase.com) 建立專案
2. 進入 SQL Editor
3. 執行 `sql/schema.sql` 中的 SQL 語句

### 2. 設定環境變數

複製 `.env.example` 為 `.env`，並填入：

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key

# Shopify
SHOPIFY_SHOP_DOMAIN=your-shop.myshopify.com
SHOPIFY_ACCESS_TOKEN=your-access-token
SHOPIFY_WEBHOOK_SECRET=your-webhook-secret

# App Settings
SECRET_KEY=your-secret-key
DEFAULT_COMMISSION_RATE=5
COOKIE_DAYS=30
MIN_PAYOUT_JPY=20000

# 短網址設定
SHORT_URL_DOMAIN=https://go.goyoulink.com
REDIRECT_TARGET=https://goyoutati.com

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password
```

### 3. 部署到 Zeabur

1. 將程式碼推送到 GitHub
2. 在 Zeabur 建立專案，選擇從 GitHub 部署
3. 設定環境變數
4. 設定自訂網域 `go.goyoulink.com`

### 4. 設定 Shopify Webhook

在 Shopify Admin 設定以下 Webhook：

| 事件 | URL |
|------|-----|
| Order creation | `https://go.goyoulink.com/webhook/shopify/orders/create` |
| Order fulfillment | `https://go.goyoulink.com/webhook/shopify/orders/fulfilled` |
| Order cancellation | `https://go.goyoulink.com/webhook/shopify/orders/cancelled` |
| Refund creation | `https://go.goyoulink.com/webhook/shopify/refunds/create` |

### 5. 加入追蹤腳本到 Shopify

在 Shopify Theme 的 `theme.liquid` 中加入：

```html
<script src="https://go.goyoulink.com/static/tracking.js"></script>
```

或透過 Shopify Script Tag API 加入。

## 系統架構

```
短網址 (go.goyoulink.com/abc123)
    ↓
記錄點擊 → 重新導向到 goyoutati.com?ref=xxx
    ↓
追蹤腳本將 ref 存入 Cookie
    ↓
客人結帳時，ref 寫入訂單
    ↓
Shopify Webhook 通知系統
    ↓
系統記錄訂單並計算佣金
```

## 管理後台

- **URL**: `https://go.goyoulink.com/admin`
- **功能**:
  - 管理代購業者
  - 查看推薦訂單
  - 確認/取消訂單狀態
  - 發放佣金

## 代購業者入口

- **URL**: `https://go.goyoulink.com/partner`
- **登入方式**: 使用推薦碼登入
- **功能**:
  - 查看推廣連結
  - 查看訂單統計
  - 查看佣金記錄

## API 端點

### 短網址

- `GET /:short_code` - 短網址重新導向
- `GET /:short_code/:product_path` - 帶商品路徑的短網址

### Webhook

- `POST /webhook/shopify/orders/create` - 新訂單
- `POST /webhook/shopify/orders/fulfilled` - 訂單出貨
- `POST /webhook/shopify/orders/cancelled` - 訂單取消
- `POST /webhook/shopify/refunds/create` - 退款

### 管理後台 API

- `GET /admin/api/stats` - 統計數據
- `GET /admin/api/affiliates` - 代購業者列表
- `GET /admin/api/affiliates/:id` - 代購業者詳情

### 代購業者 API

- `GET /partner/api/stats` - 自己的統計
- `GET /partner/api/orders` - 自己的訂單
- `GET /partner/api/clicks` - 自己的點擊記錄

## 佣金規則

- **預設比例**: 5%
- **計算基準**: 整張訂單金額
- **生效條件**: 訂單出貨後
- **退款處理**: 自動扣回佣金
- **最低提領**: ¥20,000
- **結算週期**: 每月一次
- **Cookie 有效期**: 30 天

## 開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 執行
python app.py
```

## 授權

Private - GoyouLink
