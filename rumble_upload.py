#!/usr/bin/env python3
"""
rumble_upload.py — Automated video upload to Rumble.com

Usage:
    python rumble_upload.py <video_path> [--thumbnail <path>] [--title <title>] ...

Environment variables:
    RUMBLE_EMAIL     — Rumble account email/username
    RUMBLE_PASSWORD   — Rumble account password

If --title, --description, --tags are omitted, the script looks for
metadata.json in the same directory as the video file.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ═════════════════════════════════════════════════════════════
#  Configuration
# ═════════════════════════════════════════════════════════════

RUMBLE_EMAIL    = os.environ.get('RUMBLE_EMAIL', '')
RUMBLE_PASSWORD = os.environ.get('RUMBLE_PASSWORD', '')

LOGIN_URL    = 'https://auth.rumble.com/?theme=s&redirect_uri=https%3A%2F%2Frumble.com%2F&lang=en_US'
UPLOAD_URL   = 'https://rumble.com/upload.php'
SESSION_FILE = Path('rumble_session.json')

SCREENSHOT_BEFORE = 'rumble_before_publish.png'
SCREENSHOT_AFTER  = 'rumble_after_publish.png'

# Default category value (Rumble custom select data-value)
# 14 = Comedy — adjust as needed for your podcast
DEFAULT_CATEGORY_VALUE = '14'

# Timeouts
UPLOAD_COMPLETE_TIMEOUT = 300_000   # 5 minutes for file upload
PUBLISH_REDIRECT_TIMEOUT = 60_000  # 1 minute for post-publish redirect


# ═════════════════════════════════════════════════════════════
#  Helper: logging
# ═════════════════════════════════════════════════════════════

def log(msg=''):
    print(msg, flush=True)


# ═════════════════════════════════════════════════════════════
#  Helper: find metadata alongside video
# ═════════════════════════════════════════════════════════════

def find_metadata(video_path):
    """Look for metadata.json and thumbnail in the video's directory."""
    video_dir = Path(video_path).parent
    meta_file = video_dir / 'metadata.json'

    defaults = {
        'title':       video_dir.name,
        'description': '',
        'tags':        '',
        'category':    DEFAULT_CATEGORY_VALUE,
        'thumbnail':   None,
    }

    if meta_file.exists():
        try:
            data = json.loads(meta_file.read_text())
            defaults.update(data)
        except Exception as e:
            log(f'  [metadata] Warning: could not parse {meta_file}: {e}')

    # Look for a thumbnail image if none specified
    if not defaults.get('thumbnail'):
        for name in ('thumbnail.jpg', 'thumbnail.png', 'thumb.jpg', 'thumb.png'):
            candidate = video_dir / name
            if candidate.exists():
                defaults['thumbnail'] = str(candidate)
                break

    return defaults


# ═════════════════════════════════════════════════════════════
#  RumbleUploader
# ═════════════════════════════════════════════════════════════

class RumbleUploader:

    def __init__(self, headless=True):
        self.headless   = headless
        self.playwright = None
        self.browser    = None
        self.context    = None
        self.page       = None

    # ─────────────────────────────────────────────
    #  Browser lifecycle
    # ─────────────────────────────────────────────

    def start(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        self.context = self.context_new()
        self.page = self.context.new_page()

    def stop(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def context_new(self):
        """Create a browser context with sensible defaults."""
        return self.browser.new_context(
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800},
            accept_images=True,
        )

    # ─────────────────────────────────────────────
    #  Session management
    # ─────────────────────────────────────────────

    def _has_saved_session(self):
        if not SESSION_FILE.exists():
            return False
        try:
            data = json.loads(SESSION_FILE.read_text())
            return bool(data.get('cookies'))
        except Exception:
            return False

    def _restore_session(self):
        try:
            data = json.loads(SESSION_FILE.read_text())
            self.context.add_cookies(data.get('cookies', []))
            return True
        except Exception as e:
            log(f'  [session] Restore failed: {e}')
            return False

    def _save_session(self):
        cookies = self.context.cookies()
        SESSION_FILE.write_text(json.dumps({'cookies': cookies}, indent=2))
        log(f'  Session saved to {SESSION_FILE.resolve()}')

    # ─────────────────────────────────────────────
    #  Authentication
    # ─────────────────────────────────────────────

    def _is_logged_in(self):
        """Check whether the current page shows an authenticated state."""
        try:
            # If we can see the upload form, we're logged in
            file_input = self.page.locator('input[name=Filedata]')
            return file_input.count() > 0
        except Exception:
            return False

    def _login(self):
        log('  [auth] Logging in with credentials...')
        page = self.page

        page.goto(LOGIN_URL, wait_until='networkidle')
        time.sleep(2)

        log(f'    [login-page] URL: {page.url}')
        log(f'    [login-page] Title: {page.title()}')

        # Detect bot protection
        captcha = page.locator('[id*=captcha], [class*=captcha], [data-captcha]')
        if captcha.count() > 0:
            log("    [login-page] WARNING: bot-protection marker detected: 'captcha'")

        input_count = page.locator('input').count()
        log(f'    [login-page] <input> count on page: {input_count}')

        # Fill username/email
        email_sel = 'input[name=username]'
        if page.locator(email_sel).count() > 0:
            log(f'    [login-page] email selector matched: input[name=username]')
            page.fill(email_sel, RUMBLE_EMAIL)
        else:
            page.fill('input[type=email], input[name=email]', RUMBLE_EMAIL)

        # Fill password
        page.fill('input[type=password], input[name=password]', RUMBLE_PASSWORD)

        # Submit
        page.locator(
            'button[type=submit], button:has-text("Sign in"), '
            'button:has-text("Log in"), input[type=submit]'
        ).first.click()

        # Wait for redirect away from auth page
        try:
            page.wait_for_url(
                lambda url: 'rumble.com' in url and 'auth.rumble' not in url,
                timeout=30_000,
            )
            log('  Login successful.')
            return True
        except PlaywrightTimeoutError:
            log('  Login failed — timeout waiting for redirect.')
            return False

    def _ensure_logged_in(self):
        """Restore session or log in fresh."""
        if self._has_saved_session():
            log('  Restoring saved session...')
            self._restore_session()

        # Navigate to upload page
        self.page.goto(UPLOAD_URL, wait_until='networkidle')
        time.sleep(2)

        if self._is_logged_in():
            log('  Session is valid.')
        else:
            log('  No valid session, logging in...')
            if not self._login():
                raise RuntimeError('Login failed.')
            # Navigate back to upload page after login
            self.page.goto(UPLOAD_URL, wait_until='networkidle')
            time.sleep(2)

        self._save_session()

    # ─────────────────────────────────────────────
    #  File upload
    # ─────────────────────────────────────────────

    def _upload_file(self, video_path):
        page = self.page
        log('  Waiting for upload form...')

        file_input = page.locator('input[name=Filedata]')
        file_input.wait_for(state='attached', timeout=30_000)

        file_input.set_input_files(str(video_path))
        log(f'  File selected: {Path(video_path).name}')

        log('  Waiting for upload to complete...')
        self._wait_for_upload_complete()

    def _wait_for_upload_complete(self):
        page = self.page

        # Wait for 100% indicator
        try:
            page.wait_for_selector(
                '.num_percent:has-text("100%")',
                timeout=UPLOAD_COMPLETE_TIMEOUT,
            )
            log('  Upload reached 100%.')
        except PlaywrightTimeoutError:
            # Fallback: check progress bar width
            try:
                page.wait_for_function(
                    """() => {
                        const el = document.querySelector('.green_percent');
                        return el && el.style.width === '100%';
                    }""",
                    timeout=UPLOAD_COMPLETE_TIMEOUT,
                )
                log('  Upload reached 100% (via progress bar).')
            except PlaywrightTimeoutError:
                log('  WARNING: Upload completion could not be confirmed via UI. Continuing...')

        # Extra wait for server-side processing
        time.sleep(3)

    # ─────────────────────────────────────────────
    #  Metadata
    # ─────────────────────────────────────────────

    def _fill_metadata(self, title, description, tags, category_value):
        page = self.page

        # Title
        page.fill('input[name=title]', title)
        log(f'  Title set: {title}')

        # Description
        page.fill('textarea[name=description]', description)
        log(f'  Description set ({len(description)} chars)')

        # Tags
        page.fill('input[name=tags]', tags)
        log(f'  Tags set: {tags}')

        # Category (custom select widget)
        self._select_category(category_value)

        # Visibility: Public
        public_radio = page.locator('input[name=visibility][value=public]')
        if public_radio.count() > 0 and not public_radio.first.is_checked():
            public_radio.first.check()
        log('  Visibility set: public')

    def _select_category(self, category_value):
        page = self.page

        # Click the search input to open the dropdown
        search_input = page.locator('input[name=primary-category]')
        search_input.click()
        time.sleep(0.5)

        # Find and click the matching option
        option = page.locator(f'.select-option[data-value="{category_value}"]')
        if option.count() > 0:
            label = option.first.get_attribute('data-label') or '(unknown)'
            option.first.click()
            log(f'  Category set: {label} (value={category_value})')
        else:
            log.warning(f'  Category option {category_value} not found in dropdown.')
            # Try setting the hidden value directly
            page.evaluate(
                f"document.getElementById('category_primary').value = '{category_value}';"
            )
            log(f'  Category value set directly: {category_value}')

        time.sleep(0.3)

    # ─────────────────────────────────────────────
    #  Thumbnail
    # ─────────────────────────────────────────────

    def _set_thumbnail(self, thumbnail_path):
        page = self.page
        thumb_path = Path(thumbnail_path).resolve()

        if not thumb_path.exists():
            log(f'  Thumbnail not found: {thumb_path} — skipping.')
            return

        # Click "or choose your own" to reveal custom thumbnail upload
        choose_own = page.locator('a.choose-your-own')
        if choose_own.count() > 0:
            choose_own.first.click()
            time.sleep(0.5)

        # Upload the thumbnail file
        thumb_input = page.locator('input[name=customThumb]')
        if thumb_input.count() > 0:
            thumb_input.set_input_files(str(thumb_path))
            log('  Thumbnail set.')
            time.sleep(1)
        else:
            log('  WARNING: Could not find thumbnail file input.')

    # ─────────────────────────────────────────────
    #  Licensing  ← THIS WAS MISSING
    # ─────────────────────────────────────────────

    def _select_license(self):
        """
        Select the 'Rumble Only (non-exclusive, similar to YouTube)'
        licensing option.

        The licensing options on Rumble's upload form are <A> links,
        NOT radio buttons.  You must click one before the form will
        accept submission.

        Available options:
          - Video Management (exclusive)
          - Video Management (excluding YouTube)
          - Rumble Only (non-exclusive, similar to YouTube)   ← we pick this
          - Personal Use (not monetized, not searchable)
        """
        page = self.page

        # Try several selectors for the "Rumble Only" link
        selectors = [
            'a:has-text("Rumble Only")',
            'a.greenLink:has-text("Rumble Only")',
            'a:has-text("non-exclusive")',
        ]

        clicked = False
        for sel in selectors:
            link = page.locator(sel).first
            if link.count() > 0 and link.is_visible():
                link.click()
                time.sleep(0.5)
                log('  License selected: Rumble Only (non-exclusive, similar to YouTube)')
                clicked = True
                break

        if not clicked:
            log('  WARNING: Could not find licensing option "Rumble Only".')
            log('           The form may not submit without a licensing selection.')

    # ─────────────────────────────────────────────
    #  Terms & Conditions  ← THIS WAS MISSING
    # ─────────────────────────────────────────────

    def _agree_to_terms(self):
        """
        Check the Terms-of-Service checkboxes.

        There are two checkboxes with name='crights':
          1. "You have not signed an exclusive agreement with any other parties."
          2. "Check here if you agree to our terms of service."

        BOTH must be checked or the form will not submit.
        """
        page = self.page

        crights = page.locator('input[name=crights]')
        count = crights.count()

        if count == 0:
            log('  WARNING: No terms checkboxes (input[name=crights]) found.')
            return

        for i in range(count):
            checkbox = crights.nth(i)
            if not checkbox.is_checked():
                checkbox.check()
                time.sleep(0.3)

        log(f'  Terms agreed ({count} checkbox{"es" if count != 1 else ""} checked).')

    # ─────────────────────────────────────────────
    #  Publish
    # ─────────────────────────────────────────────

    def _publish(self):
        """
        Click the submit button and verify success.

        The submit button on Rumble's upload form is:
          <input type="button" id="submitForm"
                 class="submit_content button-small update-btn"
                 value="Upload">

        Note: the button text is "Upload", NOT "Publish".
        After a successful submit, Rumble redirects to a media
        management page.
        """
        page = self.page

        # Locate the submit button by ID (most reliable)
        submit_btn = page.locator('#submitForm')

        # Fallback selectors if ID is not found
        if submit_btn.count() == 0:
            fallbacks = [
                'input.submit_content',
                'input.update-btn',
                'input[type=button][value=Upload]',
                'button:has-text("Upload")',
            ]
            for sel in fallbacks:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    submit_btn = btn
                    log(f'  Found submit button via fallback: {sel}')
                    break

        if submit_btn.count() == 0:
            log('  ! Could not find submit button')
            self._dump_debug()
            return False

        # Check if disabled
        disabled = submit_btn.first.get_attribute('disabled')
        if disabled is not None:
            log('  ! Submit button is DISABLED — a required field may be missing.')
            self._dump_debug()
            return False

        # Click it
        log('  Clicking submit button (id=submitForm, value=Upload)...')
        submit_btn.first.click()

        # ── Wait for success ──
        # After successful publish, Rumble redirects away from /upload.php
        try:
            page.wait_for_url(
                lambda url: 'upload.php' not in url,
                timeout=PUBLISH_REDIRECT_TIMEOUT,
            )
            log(f'  Publish confirmed — redirected to: {page.url}')
            return True
        except PlaywrightTimeoutError:
            pass

        # Fallback: check for success indicators on the current page
        success_selectors = [
            'text=successfully',
            'text=upload complete',
            'text=video has been',
            '.media-published',
            '.success-message',
        ]
        for sel in success_selectors:
            if page.locator(sel).count() > 0:
                log(f'  Publish confirmed — success indicator found: {sel}')
                return True

        log('  ! Could not confirm publish success.')
        self._dump_debug()
        return False

    # ─────────────────────────────────────────────
    #  Debug dump (on failure)
    # ─────────────────────────────────────────────

    def _dump_debug(self):
        """Dump page state for debugging when something goes wrong."""
        page = self.page
        log('  --- DEBUG DUMP ---')

        # Current URL
        log(f'  Current URL: {page.url}')

        # All buttons
        buttons = page.locator('button, input[type=button], input[type=submit]').all()
        log(f'  Buttons on page: {len(buttons)}')
        for i, btn in enumerate(buttons):
            try:
                outer = btn.evaluate('el => el.outerHTML.slice(0, 200)')
                log(f'    [{i}] {outer}')
            except Exception:
                pass

        # Validation errors
        errors = page.locator('.error, [class*=error], .invalid, [class*=invalid]').all()
        log(f'  Error elements: {len(errors)}')
        for i, err in enumerate(errors):
            try:
                txt = err.text_content()
                if txt and txt.strip():
                    log(f'    [error {i}] {txt.strip()[:200]}')
            except Exception:
                pass

        # Checkboxes state
        checkboxes = page.locator('input[type=checkbox]').all()
        log(f'  Checkboxes: {len(checkboxes)}')
        for i, cb in enumerate(checkboxes):
            try:
                name = cb.get_attribute('name') or '(no name)'
                checked = cb.is_checked()
                log(f'    [checkbox {i}] name={name} checked={checked}')
            except Exception:
                pass

        # Save full HTML
        try:
            html_path = Path('rumble_debug_page.html')
            html_path.write_text(page.content())
            log(f'  Full HTML saved: {html_path.resolve()}')
        except Exception:
            pass

        log('  --- END DEBUG DUMP ---')

    # ─────────────────────────────────────────────
    #  Main upload orchestration
    # ─────────────────────────────────────────────

    def upload(self, video_path, title, description, tags,
               category_value=DEFAULT_CATEGORY_VALUE,
               thumbnail_path=None):
        """
        Full upload pipeline:
          1. Login / restore session
          2. Upload video file
          3. Fill metadata (title, description, tags, category, visibility)
          4. Set thumbnail
          5. Select licensing option     ← was missing
          6. Agree to terms of service   ← was missing
          7. Click publish button
          8. Verify success
        """
        video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f'Video not found: {video_path}')

        log()
        log('============================================================')
        log('RUMBLE UPLOAD')
        log('============================================================')

        # 1. Login / restore session
        self._ensure_logged_in()

        # 2. Upload video file
        log(f'  Uploading file: {video_path.name}')
        self._upload_file(video_path)

        # 3. Fill metadata
        self._fill_metadata(title, description, tags, category_value)

        # 4. Set thumbnail
        if thumbnail_path:
            self._set_thumbnail(thumbnail_path)
        else:
            log('  No thumbnail provided — skipping.')

        # 5. Select licensing option
        self._select_license()

        # 6. Agree to terms
        self._agree_to_terms()

        # Small delay to let any JS/HTMX state settle
        time.sleep(1)

        # 7. Pre-publish screenshot
        self.page.screenshot(path=SCREENSHOT_BEFORE, full_page=True)
        log(f'  Screenshot saved: {Path(SCREENSHOT_BEFORE).resolve()}')

        # 8. Publish
        success = self._publish()

        # 9. Post-publish screenshot
        self.page.screenshot(path=SCREENSHOT_AFTER, full_page=True)
        log(f'  Screenshot saved: {Path(SCREENSHOT_AFTER).resolve()}')

        if not success:
            raise RuntimeError(
                'Could not confirm publish success. '
                f'Check {SCREENSHOT_AFTER} and rumble_debug_page.html'
            )

        log()
        log('============================================================')
        log('RUMBLE UPLOAD COMPLETE ✓')
        log('============================================================')
        log(f'  Video URL: {self.page.url}')
        log()


# ═════════════════════════════════════════════════════════════
#  CLI entry point
# ═════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Upload a video to Rumble.com'
    )
    parser.add_argument('video', help='Path to the video file')
    parser.add_argument('--title',       help='Video title')
    parser.add_argument('--description', help='Video description')
    parser.add_argument('--tags',        help='Comma-separated tags')
    parser.add_argument('--category',    default=DEFAULT_CATEGORY_VALUE,
                        help=f'Rumble category data-value (default: {DEFAULT_CATEGORY_VALUE})')
    parser.add_argument('--thumbnail',   help='Path to thumbnail image')
    parser.add_argument('--headed', action='store_true',
                        help='Run with visible browser (for debugging)')
    args = parser.parse_args()

    # Load metadata from directory if individual fields are missing
    meta = find_metadata(args.video)
    title       = args.title       or meta['title']
    description = args.description or meta['description']
    tags        = args.tags        or meta['tags']
    category    = args.category    or meta['category']
    thumbnail   = args.thumbnail   or meta['thumbnail']

    # Validate credentials
    if not RUMBLE_EMAIL or not RUMBLE_PASSWORD:
        log('ERROR: RUMBLE_EMAIL and RUMBLE_PASSWORD environment variables are required.')
        sys.exit(1)

    log(f'Uploading: {args.video}')

    # Run
    uploader = RumbleUploader(headless=not args.headed)
    try:
        uploader.start()
        uploader.upload(
            video_path=args.video,
            title=title,
            description=description,
            tags=tags,
            category_value=category,
            thumbnail_path=thumbnail,
        )
    except Exception as e:
        log()
        log('============================================================')
        log('RUMBLE UPLOAD FAILED')
        log('============================================================')
        log(f'Error: {e}')
        # Save failure screenshot
        if uploader.page:
            try:
                uploader.page.screenshot(path=SCREENSHOT_AFTER, full_page=True)
                log(f'Screenshot saved: {Path(SCREENSHOT_AFTER).resolve()}')
            except Exception:
                pass
        sys.exit(1)
    finally:
        uploader.stop()


if __name__ == '__main__':
    main()
