/**
 * GoyouLink 分潤追蹤腳本
 * 
 * 將此腳本加入 Shopify 商店的 theme.liquid 或透過 Script Tag API
 * 
 * 功能：
 * 1. 偵測網址中的 ref 參數
 * 2. 將推薦碼存入 Cookie（30 天）
 * 3. 結帳時將推薦碼寫入購物車屬性
 */

(function() {
    'use strict';
    
    // 設定
    var CONFIG = {
        cookieName: 'goyoulink_ref',
        cookieDays: 30,
        paramName: 'ref'
    };
    
    // Cookie 操作函數
    function setCookie(name, value, days) {
        var expires = '';
        if (days) {
            var date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = '; expires=' + date.toUTCString();
        }
        document.cookie = name + '=' + (value || '') + expires + '; path=/; SameSite=Lax';
    }
    
    function getCookie(name) {
        var nameEQ = name + '=';
        var ca = document.cookie.split(';');
        for (var i = 0; i < ca.length; i++) {
            var c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
        }
        return null;
    }
    
    // 從網址取得推薦碼
    function getRefFromUrl() {
        var urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(CONFIG.paramName);
    }
    
    // 更新購物車屬性
    function updateCartAttributes(refCode) {
        fetch('/cart/update.js', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attributes: {
                    'referral_code': refCode
                }
            })
        })
        .then(function(response) {
            if (response.ok) {
                console.log('[GoyouLink] Cart attributes updated with ref:', refCode);
            }
        })
        .catch(function(error) {
            console.error('[GoyouLink] Error updating cart:', error);
        });
    }
    
    // 主邏輯
    function init() {
        // 1. 檢查網址是否有 ref 參數
        var refFromUrl = getRefFromUrl();
        
        if (refFromUrl) {
            // 有新的推薦碼，存入 Cookie
            setCookie(CONFIG.cookieName, refFromUrl, CONFIG.cookieDays);
            console.log('[GoyouLink] New referral code saved:', refFromUrl);
            
            // 立即更新購物車屬性
            updateCartAttributes(refFromUrl);
        }
        
        // 2. 取得已存在的推薦碼
        var savedRef = getCookie(CONFIG.cookieName);
        
        if (savedRef) {
            console.log('[GoyouLink] Active referral code:', savedRef);
            
            // 確保購物車屬性已設定（每次頁面載入都檢查）
            // 使用延遲確保購物車已載入
            setTimeout(function() {
                updateCartAttributes(savedRef);
            }, 1000);
        }
    }
    
    // 頁面載入完成後執行
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    // 監聽購物車變化（加入商品時）
    // 這確保在任何時候加入商品都會帶上推薦碼
    var originalFetch = window.fetch;
    window.fetch = function() {
        var args = arguments;
        var url = args[0];
        
        // 監聽加入購物車的請求
        if (typeof url === 'string' && url.includes('/cart/add')) {
            var savedRef = getCookie(CONFIG.cookieName);
            if (savedRef) {
                // 在加入購物車後更新屬性
                return originalFetch.apply(this, args).then(function(response) {
                    updateCartAttributes(savedRef);
                    return response;
                });
            }
        }
        
        return originalFetch.apply(this, args);
    };
    
})();
