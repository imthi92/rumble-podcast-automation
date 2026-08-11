#!/usr/bin/env python3
"""
Rumble Upload Automation - Cat Podcast
Uploads videos to Rumble using Playwright browser automation.

One-time setup (on your machine, any day):
    python rumble_upload.py --login
    -> Browser opens, you sign in to Rumble once, session saved to rumble_session.json

After that, uploads are fully automatic (no login needed):
    python rumble_upload.py <video.mp4> <title> [description] [thumbnail.png]

Fully-automatic cloud mode (no saved session required):
    Set RUMBLE_EMAIL + RUMBLE_PASSWORD env vars and the script logs in headlessly.
    Used by the GitHub Actions workflow so nothing runs on your laptop.

IMPORTANT: Rumble has no public upload API. This automates the web upload form.
If Rumble changes their site, update SELECTORS below (run with --headed to debug).
"""

import argparse
import json
import os
import sys
import time

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rumble_session.json")

LOGIN_URL = "https://rumble.com/login"
UPLOAD_URL = "https://rumble.com/upload"

# ============================================================
# SELECTORS - update these if Rumble changes their site
# ============================================================
SELECTORS = {
    "login_email": ["input[type=email]", "input[name=username]", "#username", "input[placeholder*=mail]", "input[placeholder*=User]"],
    "login_password": ["input[type=password]", "#password"],
    "login_submit": ["button[type=submit]", "button[data-testid=login-submit]", "input[type=submit]"],
    "upload_file": ["input[type=file]", ".upload-file input", "input[name=file]"],
    "upload_title": ["input[name=title]", "#title", "input[placeholder*=title]", "input[placeholder*=Title]"],
    "upload_description": ["textarea[name=description]", "#description", "textarea[placeholder*=description]", "textarea[placeholder*=Description]"],
    "upload_tags": ["input[name=tags]", "#tags", "input[placeholder*=tags]", "input[placeholder*=Tags]"],
    "upload_publish": ["button[type=submit]", "button:has-text('Publish')", "button:has-text('Upload Video')", "button:has-text('Submit')"],
    "visibility_public": ["input[value=public]", "label:has-text('Public')", "input[name=visibility][value=public]"],
    "thumbnail_file": ["input[type=file][accept*=image]", ".thumbnail-upload input", "input[name=thumbnail]"],
}

DEFAULT_DESCRIPTION = """Cat Podcast with Simba and Meow - fully AI generated.

Simba (Marketing, confident, slightly stupid) and Meow (Finance, intelligent, sarcastic) talk about office life, workplace drama, and cat things.

New episodes daily!

#CatPodcast #SimbaAndMeow #FunnyCats #OfficeHumor"""

DEFAULT_TAGS = "cat podcast,furry cats,office cats,cat comedy,simba and meow,funny cats,office humor,workplace comedy,cat dialogue"


def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_session(state):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"  Session saved to {SESSION_FILE}")


def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright()
    except ImportError:
        print("=" * 60)
        print("Playwright not installed. One-time install:")
        print("  pip install playwright")
        print("  playwright install chromium")
        print("=" * 60)
        sys.exit(1)


def try_click(page, selectors, timeout=15000, description="element"):
    """Click the first matching selector. Returns True on success."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return True
        except Exception:
            continue
    print(f"  ! Could not find/click: {description}")
    return False


def try_fill(page, selectors, value, timeout=15000, description="field"):
    """Fill the first matching selector. Returns True on success."""
    if not value:
        return True
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.fill(value)
            return True
        except Exception:
            continue
    print(f"  ! Could not find/fill: {description}")
    return False


def is_logged_in(page):
    """Heuristic: upload page should show upload UI, not a login form."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    # Look for the file upload control (may be hidden -> check "attached")
    for sel in SELECTORS["upload_file"]:
        try:
            page.locator(sel).first.wait_for(state="attached", timeout=5000)
            return True
        except Exception:
            continue
    # If we got redirected to login, we're not logged in
    if "/login" in page.url:
        return False
    return False


def login_with_credentials(page, email, password):
    """Login to Rumble using email/password."""
    print("  [auth] Logging in with credentials...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    time.sleep(2)

    if not try_fill(page, SELECTORS["login_email"], email, description="email"):
        print("    ERROR: email field not found. Rumble may have changed their login page.")
        _screenshot(page, "rumble_debug_login")
        return False

    if not try_fill(page, SELECTORS["login_password"], password, description="password"):
        print("    ERROR: password field not found.")
        _screenshot(page, "rumble_debug_login")
        return False

    if not try_click(page, SELECTORS["login_submit"], description="login submit"):
        print("    ERROR: login submit button not found.")
        _screenshot(page, "rumble_debug_login")
        return False

    # Wait for redirect AWAY from the login page
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
    except Exception:
        pass
    time.sleep(3)

    if "/login" in page.url:
        print("    ERROR: still on login page - wrong credentials or blocked.")
        _screenshot(page, "rumble_debug_login")
        return False

    print("    Login successful.")
    return True


def _set_thumbnail(page, thumbnail_path):
    """Set thumbnail only if a dedicated thumbnail file input exists.
    Never touches the video file input (first input[type=file] on the page)."""
    try:
        file_inputs = page.locator("input[type=file]")
        count = file_inputs.count()
        if count <= 1:
            print("  ! No separate thumbnail field found, skipping thumbnail.")
            return
        # Use a dedicated image-accepting input if present
        for sel in SELECTORS["thumbnail_file"]:
            try:
                page.locator(sel).first.wait_for(state="attached", timeout=3000)
                page.locator(sel).first.set_input_files(thumbnail_path)
                print("  Thumbnail set.")
                return
            except Exception:
                continue
        # Fallback: last file input is probably the thumbnail
        file_inputs.nth(count - 1).set_input_files(thumbnail_path)
        print("  Thumbnail set (last file input).")
    except Exception as e:
        print(f"  ! Thumbnail upload skipped: {e}")


def upload_video(video_path, title, description=None, tags=None, thumbnail_path=None, headed=False):
    """Upload a video to Rumble. Returns video URL or None."""
    print("\n" + "=" * 60)
    print("RUMBLE UPLOAD")
    print("=" * 60)

    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return None

    email = os.environ.get("RUMBLE_EMAIL", "")
    password = os.environ.get("RUMBLE_PASSWORD", "")
    session = load_session()

    pw = get_playwright()
    pw.start()
    try:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context(storage_state=session) if session else browser.new_context()
        page = context.new_page()

        try:
            # --- Ensure logged in ---
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            time.sleep(2)

            if not is_logged_in(page):
                print("  No valid session, logging in...")
                if not (email and password):
                    print("  ERROR: No saved session and no RUMBLE_EMAIL/RUMBLE_PASSWORD set.")
                    print("  Run once: python rumble_upload.py --login")
                    print("  Or set env vars for cloud automation.")
                    return None
                if not login_with_credentials(page, email, password):
                    return None
                save_session(context.storage_state())

            # --- Go to upload page ---
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            time.sleep(3)

            # --- Select file ---
            print(f"  Uploading file: {os.path.basename(video_path)}")
            file_uploaded = False
            for sel in SELECTORS["upload_file"]:
                try:
                    page.locator(sel).first.wait_for(state="attached", timeout=15000)
                    page.locator(sel).first.set_input_files(video_path)
                    file_uploaded = True
                    break
                except Exception:
                    continue
            if not file_uploaded:
                print("  ERROR: file input not found.")
                _screenshot(page, "rumble_debug_upload")
                return None

            # Wait for the file to process and the form to appear
            print("  Waiting for upload form...")
            time.sleep(8)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass

            # --- Fill title ---
            if not try_fill(page, SELECTORS["upload_title"], title[:200], description="title"):
                print("  ! Title field not found - trying to continue.")

            # --- Fill description ---
            if description:
                if not try_fill(page, SELECTORS["upload_description"], description, description="description"):
                    print("  ! Description field not found - trying to continue.")

            # --- Fill tags ---
            if tags:
                if not try_fill(page, SELECTORS["upload_tags"], tags, description="tags"):
                    print("  ! Tags field not found - trying to continue.")

            # --- Set visibility to public ---
            try_click(page, SELECTORS["visibility_public"], timeout=8000, description="public visibility")

            # --- Upload thumbnail (optional, guarded) ---
            if thumbnail_path and os.path.exists(thumbnail_path):
                _set_thumbnail(page, thumbnail_path)

            # --- Publish ---
            _screenshot(page, "rumble_before_publish")
            if try_click(page, SELECTORS["upload_publish"], timeout=10000, description="publish button"):
                print("  Publish clicked - waiting for processing...")
                time.sleep(5)
                try:
                    page.wait_for_load_state("networkidle", timeout=45000)
                except Exception:
                    pass
                time.sleep(3)

                # Wait for redirect to the video page
                try:
                    page.wait_for_url(lambda url: "/video/" in url, timeout=45000)
                except Exception:
                    pass

                url = page.url
                if url and "/video/" in url:
                    _screenshot(page, "rumble_after_publish")
                    print("  Upload confirmed. URL:", url)
                    return url

            # If we got here, we can't confirm success
            _screenshot(page, "rumble_after_publish")
            for marker in ["Video uploaded", "upload successful", "successfully", "has been uploaded"]:
                if page.locator(f"text={marker}").count() > 0:
                    print(f"  Success marker found: {marker}")
                    return page.url or None

            print("  WARNING: Could not confirm success. Check rumble_after_publish.png")
            return None

        finally:
            context.close()
            browser.close()
    finally:
        pw.stop()


def _screenshot(page, name):
    """Save a screenshot for debugging."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.png")
        page.screenshot(path=path)
        print(f"  Screenshot saved: {path}")
    except Exception:
        pass


def interactive_login():
    """One-time interactive login. Saves session for future use."""
    print("=" * 60)
    print("RUMBLE ONE-TIME LOGIN")
    print("Sign in to Rumble in the browser window, then close it.")
    print("Your session will be saved to rumble_session.json")
    print("=" * 60)

    pw = get_playwright()
    pw.start()
    try:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("\nWaiting for you to log in... (browser is open)")
        print("You have 5 minutes. Close the browser window when done.")

        # Wait until user closes the browser or navigates away from /login
        deadline = time.time() + 300
        logged_in = False
        while time.time() < deadline:
            try:
                if "/login" not in page.url:
                    logged_in = True
                    print("  Login detected!")
                    break
            except Exception:
                pass
            try:
                page.wait_for_event("close", timeout=2000)
                print("  Browser closed.")
                break
            except Exception:
                continue

        if not logged_in:
            print("  Note: could not confirm login. Saving whatever session exists.")

        try:
            save_session(context.storage_state())
            print("Session saved. Uploads are now fully automatic.")
        except Exception as e:
            print(f"Could not save session: {e}")

        context.close()
        browser.close()
    finally:
        pw.stop()


def build_description(episode_title):
    return DEFAULT_DESCRIPTION.replace("Cat Podcast with Simba and Meow", f"Cat Podcast with Simba and Meow - {episode_title}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload videos to Rumble automatically.")
    parser.add_argument("--login", action="store_true", help="One-time interactive login")
    parser.add_argument("--video", help="Path to video file")
    parser.add_argument("--title", help="Video title")
    parser.add_argument("--description", help="Video description")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--thumbnail", help="Path to thumbnail image")
    parser.add_argument("--headed", action="store_true", help="Run browser visible (debugging)")

    args = parser.parse_args()

    if args.login:
        interactive_login()
        sys.exit(0)

    if not args.video:
        print("Usage:")
        print("  python rumble_upload.py --login                    # one-time setup")
        print("  python rumble_upload.py --video v.mp4 --title T    # upload")
        sys.exit(1)

    url = upload_video(
        video_path=args.video,
        title=args.title or "Cat Podcast Episode",
        description=args.description or build_description(args.title or ""),
        tags=args.tags or DEFAULT_TAGS,
        thumbnail_path=args.thumbnail,
        headed=args.headed,
    )

    if url:
        print(f"\nRUMBLE URL: {url}")
    else:
        print("\nRUMBLE UPLOAD FAILED")
        sys.exit(1)
