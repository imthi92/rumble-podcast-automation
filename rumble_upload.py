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
import re
import sys
import time

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rumble_session.json")

LOGIN_URL = "https://rumble.com/login.php"
UPLOAD_URL = "https://rumble.com/upload"

# Realistic Chrome user agent (helps pass Cloudflare's bot checks)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# ============================================================
# SELECTORS - update these if Rumble changes their site
# ============================================================
SELECTORS = {
    "login_email": ["input[type=email]", "input[name=username]", "input[name=email]", "#username", "#email", "input[placeholder*=mail]", "input[placeholder*=User]", "input[placeholder*=Email]", "input[autocomplete=username]", "input[name=user_id]"],
    "login_password": ["input[type=password]", "#password"],
    "login_submit": ["button:has-text('Log In')", "button:has-text('Sign In')", "button[type=submit]", "input[type=submit]"],
    "upload_file": ["input[type=file]", ".upload-file input", "input[name=file]"],
    "upload_title": ["input[name=title]", "#title", "input[placeholder*=title]", "input[placeholder*=Title]"],
    "upload_description": ["textarea[name=description]", "#description", "textarea[placeholder*=description]", "textarea[placeholder*=Description]"],
    "upload_tags": ["input[name=tags]", "#tags", "input[placeholder*=tags]", "input[placeholder*=Tags]"],
    "upload_publish": ["button:has-text('Publish')", "button:has-text('Upload Video')", "button:has-text('Submit')", "button:has-text('Save')", "button:has-text('Start Upload')", "button:has-text('Go Live')", "button[type=submit]", "input[type=submit]", "[role=button]:has-text('Publish')", "[role=button]:has-text('Upload')", ".btn-primary:has-text('Publish')", ".btn-primary:has-text('Upload')", "button.btn-primary", "button.publish", "button.upload-btn"],
    "visibility_public": ["label:has-text('Public')", "input[value=public]", "input[name=visibility][value=public]"],
    "thumbnail_file": ["input[name=customThumb]", "input[type=file][accept*=image]", ".thumbnail-upload input", "input[name=thumbnail]"],
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


def _page_diagnostics(page, label):
    """Print current URL, title, and whether common bot/captcha markers are present."""
    try:
        print(f"    [{label}] URL: {page.url}")
        print(f"    [{label}] Title: {page.title()}")
        content = page.content()
        for marker in ["captcha", "cf-challenge", "Checking your browser", "access denied", "Enable JavaScript", "just a moment"]:
            if marker.lower() in content.lower():
                print(f"    [{label}] WARNING: bot-protection marker detected: '{marker}'")
        inputs = page.locator("input").count()
        print(f"    [{label}] <input> count on page: {inputs}")
        for sel in SELECTORS["login_email"]:
            if page.locator(sel).first.count() > 0:
                print(f"    [{label}] email selector matched: {sel}")
                break
        else:
            print(f"    [{label}] no email-field selector matched (page structure unknown)")
    except Exception as e:
        print(f"    [{label}] diagnostics failed: {e}")


def login_with_credentials(page, email, password):
    """Login to Rumble using email/password."""
    print("  [auth] Logging in with credentials...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    time.sleep(2)
    _page_diagnostics(page, "login-page")

    # Give JS-rendered forms time to appear, then try with a longer timeout
    if not try_fill(page, SELECTORS["login_email"], email, timeout=25000, description="email"):
        print("    ERROR: email field not found. Rumble may have changed their login page.")
        _screenshot(page, "rumble_debug_login")
        return False

    if not try_fill(page, SELECTORS["login_password"], password, timeout=15000, description="password"):
        print("    ERROR: password field not found.")
        _screenshot(page, "rumble_debug_login")
        return False

    if not try_click(page, SELECTORS["login_submit"], timeout=15000, description="login submit"):
        print("    ERROR: login submit button not found.")
        _screenshot(page, "rumble_debug_login")
        return False

    # Wait for redirect AWAY from the login page
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=45000)
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


def _launch_browser(playwright, headed=False):
    """Launch Chromium with flags that avoid Cloudflare Turnstile blocking
    headless browser. Rumble's login is behind a 'Just a moment...' challenge
    that blocks plain headless Chromium unless the automation flag is disabled."""
    kwargs = dict(
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    if headed:
        return playwright.chromium.launch(headless=False, **kwargs)
    # Realistic Chrome UA keeps the challenge from bailing early
    ctx_browser = playwright.chromium.launch(headless=True, **kwargs)
    return ctx_browser


def _click_publish(page):
    """Find and click the publish/submit control. Rumble's button may be a
    <button>, <a>, <input>, or a div styled as a button, possibly below the fold.
    Also checks inside iframes."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    selectors = [
        "input.update-btn",
        "input.submit_content",
        "input[name=submit]",
        "input[type=submit]",
        "button[type=submit]",
        "button.update-btn",
        "button.submit_content",
        ".update-btn",
        ".submit_content",
        "input[type=button][class*=submit]",
        "input[type=button][class*=update]",
        "input[type=button]",
        "button:has-text('Publish')",
        "button:has-text('Upload Video')",
        "button:has-text('Submit')",
        "button:has-text('Save')",
        "button:has-text('Start Upload')",
        "button:has-text('Go Live')",
        "a:has-text('Publish')",
        "[role=button]:has-text('Publish')",
        "[role=button]:has-text('Upload')",
        "[class*=submit]:has-text('Publish')",
        "[class*=publish]",
        "[class*=upload-btn]",
        "form input[type=submit]",
    ]
    
    # Try main page first
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=5000)
            loc.click()
            print(f"  Publish clicked ({sel}).")
            return True
        except Exception:
            continue
    
    # Try inside iframes
    print("  Trying iframes for publish button...")
    iframes = page.frames
    for frame in iframes:
        if frame == page.main_frame:
            continue
        for sel in selectors:
            try:
                loc = frame.locator(sel).first
                loc.wait_for(state="visible", timeout=3000)
                loc.click()
                print(f"  Publish clicked in iframe ({sel}).")
                return True
            except Exception:
                continue
    
    return False


def _dump_interactive(page, label):
    """Print the interactive elements on the page so a failed run is self-diagnosing."""
    try:
        print(f"    [{label}] URL: {page.url}")
        print(f"    [{label}] Title: {page.title()}")
        for desc, locator in [
            ("buttons", "button"),
            ("role=button", "[role=button]"),
            ("links", "a[href]"),
            ("inputs[type!=hidden]", "input:not([type=hidden])"),
            ("textareas", "textarea"),
            ("selects", "select"),
            ("divs with click", "div[onclick], span[onclick]"),
        ]:
            loc = page.locator(locator)
            n = loc.count()
            print(f"    [{label}] {desc}: {n}")
            for i in range(min(n, 20)):
                el = loc.nth(i)
                txt = ""
                tag = el.evaluate("e => e.tagName")
                try:
                    txt = (el.inner_text() or "").replace("\n", " ")[:60]
                except Exception:
                    pass
                print(f"        [{i}] <{tag}> '{txt}' type={el.get_attribute('type')} name={el.get_attribute('name')} class={el.get_attribute('class')} href={el.get_attribute('href')}")

        # Form field values + radio/checkbox states (this is what matters for publish)
        print(f"    [{label}] form values:")
        for field, sel in [("title", "input[name=title]"), ("tags", "input[name=tags]"),
                           ("category", "input.select-search-value"), ("description", "textarea[name=description]")]:
            try:
                n = page.locator(sel).count()
                if n:
                    val = page.locator(sel).first.input_value() or "(empty)"
                    print(f"        {field} = '{val[:120]}'")
            except Exception:
                pass
        try:
            checked = []
            radios = page.locator("input[name=visibility]")
            for i in range(radios.count()):
                state = radios.nth(i).is_checked()
                val = radios.nth(i).get_attribute("value")
                checked.append(f"visibility[{i}]={'CHECKED' if state else 'unchecked'}(value={val})")
            print(f"        radios: {' '.join(checked)}")
            for box in ["input[name=isFeaturedForUser]", "input[name=sendPush]"]:
                try:
                    print(f"        {box.split('=')[-1].strip('[]')} = {page.locator(box).first.is_checked()}")
                except Exception:
                    pass
        except Exception as e:
            print(f"        (radio scan failed: {e})")

        # Visible error / required-field messages
        print(f"    [{label}] validation markers:")
        for sel in ["[class*=error]", ".error", "[class*=invalid]", "[class*=required]",
                    "[class*=warning]", ".alert", "[role=alert]", "[class*=toast]"]:
            try:
                for i in range(min(page.locator(sel).count(), 5)):
                    el = page.locator(sel).nth(i)
                    try:
                        err = (el.inner_text() or "").strip().replace("\n", " ")[:100]
                    except Exception:
                        err = "<no text>"
                    try:
                        vis = el.is_visible()
                    except Exception:
                        vis = "?"
                    if err and vis:
                        print(f"        {sel} [{i}] (visible={vis}): {err}")
            except Exception:
                continue

        # Also dump page HTML snippet around any "publish" or "upload" text
        content = page.content()
        for keyword in ["publish", "upload", "submit", "save"]:
            idx = content.lower().find(keyword)
            if idx > 0:
                snippet = content[max(0, idx-100):idx+100].replace("\n", " ")
                print(f"    [{label}] HTML around '{keyword}': ...{snippet}...")

        # The submit control itself: value, disabled state, enclosing form HTML
        for sel in ["input.update-btn", "input.submit_content", "input.update-btn, input.submit_content, input[type=submit]"]:
            try:
                el = page.locator(sel).first
                if el.count():
                    print(f"    [{label}] submit control ({sel}):")
                    print(f"        outerHTML: {el.evaluate('e => e.outerHTML')[:400]}")
                    for attr in ["disabled", "class", "value", "onclick", "id"]:
                        try:
                            print(f"        {attr} = {el.get_attribute(attr)}")
                        except Exception:
                            pass
                    try:
                        f = el.evaluate("e => (e.closest('form') || {}).outerHTML || '(no form)'")
                        print(f"        enclosing form: {f[:1200]}")
                    except Exception:
                        pass
            except Exception:
                continue
            break

        # Visible page text around the bottom of the form (where the button is)
        try:
            all_text = page.evaluate("document.body ? document.body.innerText : ''")
            idx = all_text.lower().find("required")
            tail = all_text[-800:]
            print(f"    [{label}] body text tail: ...{tail.replace(chr(10), ' | ')}")
            if idx >= 0:
                print(f"    [{label}] 'required' context: ...{all_text[max(0,idx-200):idx+200].replace(chr(10), ' | ')}")
        except Exception:
            pass
    except Exception as e:
        print(f"    [{label}] dump failed: {e}")


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
    playwright = pw.start()
    try:
        browser = _launch_browser(playwright, headed=headed)
        context = browser.new_context(
            storage_state=session,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
        ) if session else browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
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
            time.sleep(10)
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except Exception:
                pass
            
            # Wait for upload progress to complete (look for progress indicators)
            print("  Waiting for upload to complete...")
            for _ in range(30):  # Wait up to 30 seconds for upload to complete
                try:
                    # Check if upload progress is still showing
                    progress = page.locator("[class*=progress], [class*=uploading], text=Uploading, text=100%")
                    if progress.count() == 0:
                        break
                    # Check if any progress text shows 100%
                    content = page.content()
                    if "100%" in content or "complete" in content.lower():
                        break
                except Exception:
                    pass
                time.sleep(1)
            time.sleep(3)  # Extra wait after upload completes
            
            # --- Fill title (Rumble limit is 100 chars) ---
            if not try_fill(page, SELECTORS["upload_title"], title[:100], description="title"):
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
            print("  Looking for publish button...")
            _dump_interactive(page, "before-publish")
            _screenshot(page, "rumble_before_publish")
            if _click_publish(page):
                print("  Publish clicked - waiting for processing...")
                time.sleep(5)
                try:
                    page.wait_for_load_state("networkidle", timeout=45000)
                except Exception:
                    pass
                time.sleep(3)

                # Wait for redirect to the video page
                # Rumble video URLs look like https://rumble.com/vXXXXX-title-slug.html
                # (NOT "/video/", so use a regex matching the video ID + slug dash.
                # "videos" (listing) is excluded because it has no dash after the v.)
                video_url_re = re.compile(r"rumble\.com/v[a-zA-Z0-9]+-")
                try:
                    page.wait_for_url(
                        lambda url: bool(video_url_re.search(url)), timeout=45000
                    )
                except Exception:
                    pass

                url = page.url
                if url and video_url_re.search(url):
                    _screenshot(page, "rumble_after_publish")
                    print("  Upload confirmed. URL:", url)
                    return url

            # If we got here, we can't confirm success. Diagnose the form state.
            _dump_interactive(page, "upload-form")
            _screenshot(page, "rumble_after_publish")
            for marker in ["Video uploaded", "upload successful", "successfully", "has been uploaded"]:
                if page.locator(f"text={marker}").count() > 0:
                    print(f"  Success marker found: {marker}")
                    return page.url or None

            print("  WARNING: Could not confirm success. Check rumble_after_publish.png")
            return None

        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass
    finally:
        try:
            playwright.stop()
        except Exception:
            pass


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
    playwright = pw.start()
    try:
        browser = _launch_browser(playwright, headed=True)
        context = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("\nWaiting for you to log in... (browser is open)")
        print("You have 5 minutes. Close the browser window when done.")

        # Wait until user closes the browser or navigates away from /login
        deadline = time.time() + 300
        logged_in = False
        browser_open = True
        while time.time() < deadline and browser_open:
            try:
                if "/login" not in page.url:
                    logged_in = True
                    print("  Login detected!")
                    break
            except Exception:
                pass
            try:
                page.wait_for_event("close", timeout=2000)
                print("  Browser window closed.")
                browser_open = False
            except Exception:
                continue

        if browser_open:
            if not logged_in:
                print("  Note: could not confirm login. Saving whatever session exists.")
            try:
                save_session(context.storage_state())
                print("Session saved. Uploads are now fully automatic.")
            except Exception as e:
                print(f"Could not save session: {e}")
        else:
            print("  Session NOT saved (browser closed before login completed).")
            print("  Re-run: python rumble_upload.py --login")

        try:
            context.close()
            browser.close()
        except Exception:
            pass
    finally:
        playwright.stop()


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
