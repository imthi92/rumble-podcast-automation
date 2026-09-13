#!/usr/bin/env python3
"""
Rumble Auto Cookie Capture
Opens browser, waits 90 seconds for manual login, then auto-captures cookies.
"""
import json
import os
import sys
import time

def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("=" * 60)
    print("  RUMBLE AUTO COOKIE CAPTURE")
    print("=" * 60)
    print()
    print("  1. Browser will open to Rumble login")
    print("  2. Log in MANUALLY in the browser window")
    print("  3. After login, navigate to https://rumble.com/account/videos")
    print("  4. Cookies auto-capture after 90 seconds")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://rumble.com/login")
        print("  Browser opened. You have 90 seconds to log in...")
        print()

        # Wait 90 seconds for user to log in
        for i in range(18):
            remaining = 90 - (i * 5)
            print(f"  Time remaining: {remaining}s", end="\r")
            time.sleep(5)

        print()
        print("  Time's up! Capturing cookies...")

        # Navigate to confirm login
        page.goto("https://rumble.com/account/videos", wait_until="networkidle")
        time.sleep(3)

        title = page.title()
        url = page.url
        print(f"  Current page: {url}")
        print(f"  Page title: {title}")

        if "login" in url.lower() or "auth" in url.lower():
            print()
            print("  WARNING: Not logged in! Cookies may not work.")
            print("  Try again and make sure to log in before time runs out.")

        cookies = context.cookies()
        browser.close()

    if not cookies:
        print("  ERROR: No cookies captured.")
        sys.exit(1)

    # Filter to rumble.com cookies
    rumble_cookies = [c for c in cookies if "rumble.com" in c.get("domain", "")]

    print(f"\n  Total cookies: {len(cookies)}")
    print(f"  Rumble cookies: {len(rumble_cookies)}")

    # Clean cookies
    clean_cookies = []
    all_cookies = cookies
    for c in all_cookies:
        clean = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
        }
        if c.get("httpOnly"):
            clean["httpOnly"] = True
        if c.get("secure"):
            clean["secure"] = True
        if c.get("sameSite"):
            clean["sameSite"] = c["sameSite"]
        clean_cookies.append(clean)

    json_str = json.dumps(clean_cookies, separators=(',', ':'))

    # Verify
    parsed = json.loads(json_str)
    assert len(parsed) == len(clean_cookies)

    # Save
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rumble_cookies_clean.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"\n  Saved to: {out_path}")
    print(f"  JSON size: {len(json_str)} chars")
    print()

    # Check key cookies
    key_names = ["a_s", "e_s", "u_s", "ui_t"]
    print("  Key cookies:")
    for name in key_names:
        found = any(c["name"] == name for c in rumble_cookies)
        status = "FOUND" if found else "MISSING"
        print(f"    {name}: {status}")

    print()
    print("=" * 60)
    print("  NEXT: Tell me when done and I'll set the GitHub secret!")
    print("=" * 60)

if __name__ == "__main__":
    main()
