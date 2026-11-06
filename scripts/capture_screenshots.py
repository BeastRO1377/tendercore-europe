#!/usr/bin/env python3
"""Capture README screenshots against the *real FastAPI app* using an in-process ASGI bridge.

Browser network access is not required. No live TED calls are made; examples are synthetic.
Requires: pip install -r requirements-dev.txt && python -m playwright install chromium
"""
from __future__ import annotations

import sys
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as application  # noqa: E402

# The browser runs on an offline page; intercept only same-origin API calls and
# serve them directly from the real FastAPI app. A raw file:// or about:blank
# page without this bridge generates "Failed to parse URL from /api/countries".
API_BRIDGE = """<script>
window.__test_storage = { getItem: () => null, setItem: () => {} };
window.fetch = async (resource, options = {}) => {
  const url = new URL(String(resource), 'http://testserver');
  if (!url.pathname.startsWith('/api/')) throw Error('Unexpected request: ' + url.pathname);
  const result = await window.__asgiCall(url.pathname + url.search,
                                        options.method || 'GET', options.body || null);
  return new Response(result.body, {
    status: result.status,
    headers: {'Content-Type': result.content_type}
  });
};
</script>"""


def build_document() -> str:
    root = ROOT / 'static'
    html = (root / 'index.html').read_text(encoding='utf-8')
    for css in ('styles.css', 'design-system.css'):
        html = html.replace(
            f'<link rel="stylesheet" href="/static/{css}">',
            f'<style>{(root / css).read_text(encoding="utf-8")}</style>',
        )
    for js in ('app.js', 'tax_v04_ui.js'):
        content = (root / js).read_text(encoding='utf-8')
        if js == 'app.js':
            content = content.replace('localStorage.', 'window.__test_storage.')
        html = html.replace(f'<script src="/static/{js}" defer></script>', f'<script>{content}</script>')
    return html.replace('</head>', API_BRIDGE + '</head>')


def run() -> None:
    target = ROOT / 'docs' / 'screenshots'
    target.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='tendercore-screenshots-') as work:
        original_db = application.DB
        application.DB = Path(work) / 'screenshots.sqlite3'
        try:
            with TestClient(application.app) as client:
                def handle(path: str, method: str, body: str | None):
                    res = client.request(
                        method,
                        path,
                        content=body,
                        headers={'Content-Type': 'application/json'} if body else None,
                    )
                    if res.status_code >= 400:
                        raise AssertionError(f'API returned HTTP {res.status_code}: {method} {path}')
                    return {'status': res.status_code,
                            'body': res.text,
                            'content_type': res.headers.get('content-type', 'application/json')}

                with sync_playwright() as p:
                    executable = which('chromium') or which('chromium-browser')
                    opts = {'executable_path': executable} if executable else {}
                    browser = p.chromium.launch(headless=True, args=['--no-sandbox'], **opts)
                    try:
                        page = browser.new_page(viewport={'width': 1440, 'height': 900}, device_scale_factor=1)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
                        page.expose_function('__asgiCall', handle)
                        page.set_content(build_document(), wait_until='domcontentloaded')
                        page.wait_for_function("document.querySelectorAll('#country-grid input').length === 27")
                        page.locator('#language').select_option('en')
                        page.locator('#theme').select_option('light')
                        page.locator('#demo-toggle').click()
                        page.wait_for_function("document.querySelectorAll('.tender-card').length >= 2")
                        assert page.locator('#demo-warning').is_visible(), 'Demo disclaimer missing'
                        assert not page.locator('#toast').is_visible(), f"Visible error: {page.locator('#toast').inner_text()}"
                        assert not errors, f'Browser errors: {errors}'
                        page.screenshot(path=str(target / 'dashboard.png'), full_page=True)
                        print('Dashboard: API-backed demo cards, no errors')

                        page.locator('.navlink[data-page="criteria"]').click()
                        page.wait_for_function("document.querySelector('#country-grid').children.length > 0")
                        assert not page.locator('#toast').is_visible(), 'Toast appeared on settings'
                        assert not errors, f'Browser errors: {errors}'
                        page.screenshot(path=str(target / 'settings.png'), full_page=True)
                        print('Settings: data populated, no errors')

                        page.locator('.navlink[data-page="tenders"]').click()
                        page.locator('#theme').select_option('dark')
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(target / 'dashboard-dark.png'), full_page=True)
                        assert not page.locator('#toast').is_visible(), 'Toast appeared in dark mode'
                        assert not errors, f'Browser errors: {errors}'
                        print('Dark theme: captured')
                    finally:
                        browser.close()
        finally:
            application.DB = original_db


if __name__ == '__main__':
    run()
