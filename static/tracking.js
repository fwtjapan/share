/**
 * GoyouLink 分潤追蹤腳本
 *
 * 將此腳本加入 Shopify 商店的 theme.liquid 或透過 Script Tag API
 *
 * 功能：
 * 1. 偵測網址中的 ref 參數
 * 2. 將推薦碼存入 Cookie
 * 3. 把推薦碼寫入購物車屬性，讓它隨訂單送到後端
 *
 * ── 本次修正 ──────────────────────────────────────────────
 * 1. 原本只攔截 window.fetch。大量 Shopify 主題與 app 是用 XMLHttpRequest
 *    加入購物車，那些請求完全不經過被攔截的 fetch，導致加購後不會補寫屬性。
 *    現在 fetch 與 XHR 都攔截。
 * 2. 原本用固定的 setTimeout(..., 1000) 賭購物車已就緒，是 race condition，
 *    而且失敗完全沒有重試（.catch 只印一行 console.error）。
 *    現在改成寫入後讀回 /cart.js 驗證，失敗會退避重試。
 * 3. 原本 fetch 攔截只比對字串 url，若傳入的是 Request 物件會漏掉。
 * 4. 屬性名稱改為常數，與後端 extract_ref_code() 的比對清單對齊，
 *    並同時寫入 'ref' 與 'referral_code' 兩個 key 增加容錯。
 * ─────────────────────────────────────────────────────────
 */

(function () {
    'use strict';

    var CONFIG = {
        cookieName: 'goyoulink_ref',
        cookieDays: 30,
        paramName: 'ref',
        // 這兩個名稱必須與後端 routes/webhook.py 的 extract_ref_code() 一致
        attrNames: ['ref', 'referral_code'],
        maxRetries: 4
    };

    // ---------- Cookie ----------
    function setCookie(name, value, days) {
        var expires = '';
        if (days) {
            var date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = '; expires=' + date.toUTCString();
        }
        document.cookie = name + '=' + encodeURIComponent(value || '') + expires +
            '; path=/; SameSite=Lax';
    }

    function getCookie(name) {
        var nameEQ = name + '=';
        var ca = document.cookie.split(';');
        for (var i = 0; i < ca.length; i++) {
            var c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1, c.length);
            if (c.indexOf(nameEQ) === 0) {
                return decodeURIComponent(c.substring(nameEQ.length, c.length));
            }
        }
        return null;
    }

    function getRefFromUrl() {
        try {
            return new URLSearchParams(window.location.search).get(CONFIG.paramName);
        } catch (e) {
            return null;
        }
    }

    // ---------- 購物車屬性 ----------
    var writing = false;

    function buildAttributes(refCode) {
        var attrs = {};
        CONFIG.attrNames.forEach(function (k) { attrs[k] = refCode; });
        return attrs;
    }

    /**
     * 寫入購物車屬性，然後讀回 /cart.js 驗證是否真的存進去了。
     * 沒寫成功就退避重試（Shopify 對空購物車設定 attributes 不保證持久，
     * 所以在顧客尚未加入任何商品前很可能失敗）。
     */
    function updateCartAttributes(refCode, attempt) {
        if (!refCode || writing) return;
        attempt = attempt || 0;
        writing = true;

        fetch('/cart/update.js', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ attributes: buildAttributes(refCode) })
        })
            .then(function (response) {
                if (!response.ok) throw new Error('cart/update.js 回應 ' + response.status);
                return fetch('/cart.js', { credentials: 'same-origin' });
            })
            .then(function (r) { return r.json(); })
            .then(function (cart) {
                writing = false;
                var ok = cart && cart.attributes &&
                    CONFIG.attrNames.some(function (k) { return cart.attributes[k] === refCode; });

                if (ok) {
                    console.log('[GoyouLink] 推薦碼已寫入購物車:', refCode);
                } else if (attempt < CONFIG.maxRetries) {
                    // 購物車可能還沒建立，退避後重試
                    var delay = Math.pow(2, attempt) * 500;
                    setTimeout(function () {
                        updateCartAttributes(refCode, attempt + 1);
                    }, delay);
                } else {
                    console.warn('[GoyouLink] 推薦碼寫入購物車失敗，已達重試上限');
                }
            })
            .catch(function (error) {
                writing = false;
                if (attempt < CONFIG.maxRetries) {
                    setTimeout(function () {
                        updateCartAttributes(refCode, attempt + 1);
                    }, Math.pow(2, attempt) * 500);
                } else {
                    console.error('[GoyouLink] 更新購物車失敗:', error);
                }
            });
    }

    function currentRef() {
        return getCookie(CONFIG.cookieName);
    }

    // ---------- 攔截加入購物車 ----------
    function looksLikeCartMutation(url) {
        if (!url) return false;
        var u = String(url);
        // 只針對「加入 / 變更購物車」，不含我們自己呼叫的 /cart/update.js（會無限迴圈）
        return u.indexOf('/cart/add') !== -1 || u.indexOf('/cart/change') !== -1;
    }

    function afterCartMutation() {
        var ref = currentRef();
        if (ref) {
            // 稍等一下讓 Shopify 那邊的購物車寫入完成
            setTimeout(function () { updateCartAttributes(ref, 0); }, 200);
        }
    }

    // fetch 攔截（含 Request 物件形式）
    if (window.fetch) {
        var originalFetch = window.fetch;
        window.fetch = function () {
            var args = arguments;
            var first = args[0];
            var url = (first && typeof first === 'object' && first.url) ? first.url : first;

            var isCartAdd = typeof url === 'string' && looksLikeCartMutation(url);

            var promise = originalFetch.apply(this, args);
            if (isCartAdd) {
                promise.then(function (response) {
                    afterCartMutation();
                    return response;
                }).catch(function () { /* 不影響原本流程 */ });
            }
            return promise;
        };
    }

    // XMLHttpRequest 攔截（大量舊主題與 app 走這條）
    if (window.XMLHttpRequest) {
        var origOpen = XMLHttpRequest.prototype.open;
        var origSend = XMLHttpRequest.prototype.send;

        XMLHttpRequest.prototype.open = function (method, url) {
            this.__goyoulinkCartAdd = looksLikeCartMutation(url);
            return origOpen.apply(this, arguments);
        };

        XMLHttpRequest.prototype.send = function () {
            if (this.__goyoulinkCartAdd) {
                this.addEventListener('load', function () {
                    if (this.status >= 200 && this.status < 300) {
                        afterCartMutation();
                    }
                });
            }
            return origSend.apply(this, arguments);
        };
    }

    // ---------- 主邏輯 ----------
    function init() {
        var refFromUrl = getRefFromUrl();

        if (refFromUrl) {
            // 注意：這是 last-click 歸因 —— 顧客若先點 A 的連結、後點 B 的，
            // 佣金全歸 B。若要改成 first-click，在這裡加上
            // `if (!getCookie(CONFIG.cookieName))` 判斷即可。
            setCookie(CONFIG.cookieName, refFromUrl, CONFIG.cookieDays);
            console.log('[GoyouLink] 已記錄推薦碼:', refFromUrl);
        }

        var savedRef = currentRef();
        if (savedRef) {
            updateCartAttributes(savedRef, 0);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
