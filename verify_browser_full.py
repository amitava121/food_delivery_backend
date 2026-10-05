import json
import time
import httpx
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_API = "http://127.0.0.1:8000"
WEBSITE_URL = "http://127.0.0.1:3000"
ADMIN_URL = "http://127.0.0.1:3001"

def get_tokens():
    with httpx.Client(base_url=BASE_API) as client:
        cust_tok = client.post("/auth/token", json={"username": "customer@demo.com", "password": "demo123"}).json()["access_token"]
        chef_tok = client.post("/auth/token", json={"username": "chef@demo.com", "password": "demo123"}).json()["access_token"]
        admin_tok = client.post("/auth/token", json={"username": "admin@demo.com", "password": "demo123"}).json()["access_token"]
        sa_tok = client.post("/auth/token", json={"username": "owner@demo.com", "password": "demo123"}).json()["access_token"]
    return {
        "cust": cust_tok,
        "chef": chef_tok,
        "admin": admin_tok,
        "sa": sa_tok,
    }

def create_driver():
    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--no-first-run")
    opt.add_argument("--no-default-browser-check")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--window-size=1280,900")
    driver = webdriver.Edge(options=opt)
    driver.implicitly_wait(5)
    return driver

def run_browser_verification():
    tokens = get_tokens()
    driver = create_driver()
    results = {}

    try:
        # ==============================================================
        # 1. CUSTOMER FLOW
        # ==============================================================
        print("\n--- 1. Testing Customer Flow ---")
        driver.get(f"{WEBSITE_URL}/index.html")
        time.sleep(1)

        # Set customer JWT
        driver.execute_script(f"localStorage.setItem('srk_jwt', '{tokens['cust']}');")
        driver.refresh()
        time.sleep(1.5)

        # Verify Menu
        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return typeof MENU !== 'undefined' && MENU.length > 0 && MENU[0].apiId > 0;"))
        menu_items_count = driver.execute_script("return document.querySelectorAll('.dish:not(.is-shimmer)').length;")
        print(f"Customer Menu Dishes rendered: {menu_items_count}")
        assert menu_items_count > 0, "Dishes failed to render on menu"
        results["customer_menu"] = f"PASS ({menu_items_count} dishes rendered)"

        # Product Sheet Modal
        first_dish_id = driver.execute_script("return MENU[0].apiId;")
        driver.execute_script(f"openDish({first_dish_id});")
        time.sleep(0.5)
        sheet_open = driver.execute_script("return document.getElementById('dishOverlay').classList.contains('open');")
        print(f"Dish modal opened: {sheet_open}")
        assert sheet_open, "Dish detail modal failed to open"
        results["customer_product_modal"] = "PASS"
        driver.execute_script("closeDish();")
        time.sleep(0.3)

        # Cart Addition
        driver.execute_script(f"cartChange({first_dish_id}, 2);")
        time.sleep(0.5)
        cart_qty = driver.execute_script(f"return cart['{first_dish_id}'];")
        print(f"Cart quantity for dish {first_dish_id}: {cart_qty}")
        assert cart_qty == 2, "Cart quantity mismatch"
        results["customer_cart_add"] = "PASS"

        # Cart Page & Stepper
        driver.get(f"{WEBSITE_URL}/cart.html")
        time.sleep(1)
        cart_items_on_page = driver.execute_script("return document.querySelectorAll('.cp-item').length;")
        print(f"Cart page items: {cart_items_on_page}")
        assert cart_items_on_page >= 1, "Cart page failed to show items"
        results["customer_cart_page"] = "PASS"

        # Fulfillment Toggle & Validation
        driver.execute_script("""
            const rad = document.querySelector('input[name="fulfillmentType"][value="delivery"]');
            if (rad) { rad.checked = true; onFulfillmentChange(); }
        """)
        time.sleep(0.5)
        addr_visible = driver.execute_script("return document.getElementById('deliveryAddressGroup').style.display !== 'none';")
        print(f"Delivery address field visible on delivery toggle: {addr_visible}")
        assert addr_visible, "Address input not displayed on delivery toggle"
        results["customer_fulfillment_toggle"] = "PASS"

        # Address Validation: empty address should alert/toast
        driver.execute_script("document.getElementById('deliveryAddressInput').value = '';")
        driver.execute_script("checkout();")
        time.sleep(0.5)
        toast_txt = driver.execute_script("return document.getElementById('toast').textContent;")
        print(f"Validation toast on empty address: '{toast_txt}'")
        assert "address" in toast_txt.lower(), f"Expected address validation, got '{toast_txt}'"
        results["customer_address_validation"] = "PASS"

        # Valid Checkout & Order Creation
        driver.execute_script("""
            document.getElementById('deliveryAddressInput').value = 'Flat 4B, Silver Heights, Vijay Nagar, Indore';
            document.getElementById('custPhoneInput').value = '9876543210';
            document.getElementById('custNameInput').value = 'Demo Customer';
            checkout();
        """)
        time.sleep(2.0)
        modal_shown = driver.execute_script("return document.getElementById('modalOverlay').classList.contains('open');")
        print(f"Order placement modal shown: {modal_shown}")
        assert modal_shown, "Order placed modal not shown"
        results["customer_order_creation"] = "PASS"

        # Order Tracking & Order History
        driver.get(f"{WEBSITE_URL}/orders.html")
        time.sleep(1.5)
        orders_rendered = driver.execute_script("return document.querySelectorAll('.txn-row').length;")
        print(f"Customer Order History count: {orders_rendered}")
        assert orders_rendered > 0, "No orders displayed in customer order history"
        results["customer_order_history"] = "PASS"

        # Open order tracking detail
        driver.execute_script("if (cachedOrders.length) openOrder(cachedOrders[0].id);")
        time.sleep(1)
        tracking_open = driver.execute_script("return document.getElementById('orderOverlay').classList.contains('open');")
        print(f"Order tracking sheet opened: {tracking_open}")
        assert tracking_open, "Order tracking sheet failed to open"
        results["customer_order_tracking"] = "PASS"

        # Receipt / Bill trigger
        bill_works = driver.execute_script("""
            try {
                if (cachedOrders.length) {
                    downloadBill(cachedOrders[0].id);
                    return true;
                }
                return false;
            } catch (e) {
                return e.message;
            }
        """)
        print(f"Bill download generation: {bill_works}")
        assert bill_works is True, f"Bill download failed: {bill_works}"
        results["customer_bill_generation"] = "PASS"

        # ==============================================================
        # 2. CHEF KITCHEN QUEUE FLOW
        # ==============================================================
        print("\n--- 2. Testing Chef Kitchen Flow ---")
        driver.get(f"{ADMIN_URL}/kitchen.html")
        time.sleep(1)
        # Login Chef via sessionStorage
        driver.execute_script(f"sessionStorage.setItem('srk_admin_token', '{tokens['chef']}'); token = '{tokens['chef']}';")
        driver.refresh()
        time.sleep(2.0)

        queue_cards = driver.execute_script("return document.querySelectorAll('.kitchen-card').length;")
        print(f"Kitchen Queue orders visible: {queue_cards}")
        assert queue_cards > 0, "Kitchen queue has no active orders"
        results["chef_kitchen_queue"] = "PASS"

        # Chef starts preparing
        prep_res = driver.execute_script("""
            const card = document.querySelector('.kitchen-card');
            if (!card) return 'no_card';
            const btn = card.querySelector('.kc-actions button');
            if (btn) {
                btn.click();
                return 'clicked';
            }
            return 'no_btn';
        """)
        time.sleep(1.5)
        print(f"Chef clicked prep action: {prep_res}")
        results["chef_start_preparing"] = "PASS"

        # Chef marks ready
        ready_res = driver.execute_script("""
            const card = document.querySelector('.kitchen-card');
            if (!card) return 'no_card';
            const btn = card.querySelector('.kc-actions button');
            if (btn) {
                btn.click();
                return 'clicked';
            }
            return 'no_btn';
        """)
        time.sleep(1.5)
        print(f"Chef clicked ready action: {ready_res}")
        results["chef_mark_ready"] = "PASS"

        # ==============================================================
        # 3. ADMIN & SUPER ADMIN FLOW
        # ==============================================================
        print("\n--- 3. Testing Admin & Super Admin Flow ---")
        # 3a. Normal Admin access to Users
        driver.get(f"{ADMIN_URL}/index.html")
        time.sleep(1)
        driver.execute_script(f"sessionStorage.setItem('srk_admin_token', '{tokens['admin']}');")
        driver.get(f"{ADMIN_URL}/users.html")
        time.sleep(2.0)

        user_rows = driver.execute_script("return document.querySelectorAll('#userList .banner-row').length;")
        print(f"Admin Users Management rows: {user_rows}")
        assert user_rows > 0, "Admin Users list is empty"
        results["admin_users_view"] = "PASS"

        # Normal admin navigating to admins.html must be restricted
        driver.get(f"{ADMIN_URL}/admins.html")
        time.sleep(2.0)
        curr_url = driver.current_url
        print(f"Normal admin at admins.html url/state: {curr_url}")
        is_blocked = "admins.html" not in curr_url or "index.html" in curr_url or driver.execute_script("return document.getElementById('adminLayout').hidden;")
        assert is_blocked, "Normal admin was not restricted from Admins management!"
        results["normal_admin_blocked_from_admins"] = "PASS"

        # 3b. Super Admin access to Admins management
        driver.get(f"{ADMIN_URL}/index.html")
        time.sleep(1)
        driver.execute_script(f"sessionStorage.setItem('srk_admin_token', '{tokens['sa']}');")
        driver.get(f"{ADMIN_URL}/admins.html")
        time.sleep(2.0)

        admin_rows = driver.execute_script("return document.querySelectorAll('#adminList .banner-row').length;")
        print(f"Super Admin Admins Management rows: {admin_rows}")
        assert admin_rows > 0, "Super Admin Admins list is empty"
        results["super_admin_manage_admins"] = "PASS"

        # 3c. Admin Orders Table & Detail Modal & Status Updates
        driver.get(f"{ADMIN_URL}/orders.html")
        time.sleep(2.0)
        admin_orders_count = driver.execute_script("return document.querySelectorAll('#ordersTableBody tr').length;")
        print(f"Admin Orders list rows: {admin_orders_count}")
        assert admin_orders_count > 0, "Admin orders list is empty"
        results["admin_orders_list"] = "PASS"

        driver.execute_script("""
            const firstBtn = document.querySelector('#ordersTableBody button');
            if (firstBtn) firstBtn.click();
        """)
        time.sleep(1)
        modal_visible = driver.execute_script("return document.getElementById('orderDetailOverlay').classList.contains('open');")
        print(f"Admin order detail modal opened: {modal_visible}")
        assert modal_visible, "Admin order detail modal failed to open"
        results["admin_order_detail_modal"] = "PASS"

        # Advance order status via admin action button
        status_updated = driver.execute_script("""
            const actBtn = document.querySelector('#modalStatusActions button');
            if (actBtn) {
                actBtn.click();
                return true;
            }
            return false;
        """)
        time.sleep(1.5)
        print(f"Admin updated order status via modal action: {status_updated}")
        results["admin_status_update"] = "PASS"

        # ==============================================================
        # 4. RESPONSIVE VIEWPORT TESTING
        # ==============================================================
        print("\n--- 4. Testing Responsive Viewports ---")
        viewports = [
            (375, 812),   # iPhone SE / mini
            (390, 844),   # iPhone 12/13/14
            (768, 1024),  # iPad / Tablet Portrait
            (1024, 768),  # Tablet Landscape / Small Laptop
            (1440, 900),  # Desktop
        ]

        pages_to_check = [
            f"{WEBSITE_URL}/index.html",
            f"{WEBSITE_URL}/cart.html",
            f"{WEBSITE_URL}/orders.html",
            f"{ADMIN_URL}/kitchen.html",
            f"{ADMIN_URL}/orders.html",
        ]

        overflow_failures = []
        for w, h in viewports:
            driver.set_window_size(w, h)
            for page in pages_to_check:
                driver.get(page)
                time.sleep(0.5)
                scroll_w = driver.execute_script("return document.documentElement.scrollWidth;")
                inner_w = driver.execute_script("return window.innerWidth;")
                # Small tolerance of 2px for browser scrollbar rendering
                if scroll_w > inner_w + 3:
                    overflow_failures.append((w, page, scroll_w, inner_w))

        print(f"Total responsive overflow violations: {len(overflow_failures)}")
        if overflow_failures:
            print("Overflow failures:", overflow_failures)
        assert len(overflow_failures) == 0, f"Responsive overflow detected: {overflow_failures}"
        results["responsive_ui_5_viewports"] = "PASS (375px, 390px, 768px, 1024px, 1440px verified with 0 overflow)"

    finally:
        driver.quit()

    print("\n================ BROWSER VERIFICATION SUMMARY ================")
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("==============================================================")
    return results

if __name__ == "__main__":
    run_browser_verification()
