"""Offline responsive UI contract. Run with `pip install playwright`, Chromium installed.
No external TED access; no claims about correctness of live data.
"""
from __future__ import annotations
from pathlib import Path
from shutil import which
import json
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / "static"
html = (ROOT / "index.html").read_text(encoding="utf-8")
for name in ("styles.css", "design-system.css"):
    html = html.replace(
        f'<link rel="stylesheet" href="/static/{name}">',
        f'<style>{(ROOT / name).read_text(encoding="utf-8")}</style>',
    )
html = html.replace(
    '<script src="/static/app.js" defer></script>',
    '<script>window.__test_storage={getItem:()=>null,setItem:()=>{}};</script>'
    + '<script>'
    + (ROOT / "app.js").read_text(encoding="utf-8").replace("localStorage.", "window.__test_storage.")
    + '</script>',
)
html = html.replace(
    '<script src="/static/tax_v04_ui.js" defer></script>',
    '<script>' + (ROOT / "tax_v04_ui.js").read_text(encoding="utf-8") + '</script>',
)
results = []
OUTPUT = BASE / "out" / "ui-regression"
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=which("chromium") or which("chromium-browser") or None, args=["--no-sandbox"])
    for width, height in [(1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 700)]:
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.set_content(html, wait_until="domcontentloaded")
        page.wait_for_timeout(30)
        page.evaluate("applyI18n()")
        for lang in ("ru", "en"):
            for theme in ("system", "light", "dark"):
                page.locator("#language").select_option(lang)
                page.locator("#theme").select_option(theme)
                for tab in ("tenders", "criteria", "analytics", "economics", "about"):
                    if width <= 660:
                        page.locator("#mobile-menu-toggle").click()
                        page.locator(f'#primary-sidebar [data-page="{tab}"]').click()
                        if page.locator("#mobile-menu-toggle").get_attribute("aria-expanded") != "false":
                            raise AssertionError(f"navigation remained open: {tab}, {width}")
                    else:
                        page.locator(f'.navlink[data-page="{tab}"]').click()
                    observed = page.evaluate("""() => {
                        const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
                        const content = document.querySelector('.content');
                        const read = selector => [...content.querySelectorAll(selector)].filter(visible).map(e=>({
                           id:e.id||e.name||e.textContent.trim().slice(0,24),
                           w:Math.round(e.getBoundingClientRect().width),h:Math.round(e.getBoundingClientRect().height)
                        }));
                        return {overflow:document.documentElement.scrollWidth>innerWidth+1,
                            inputs:read('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select'),
                            checks:read('input[type=checkbox]'),
                            buttons:read('button.btn,button.text-button,.view-segment button'),
                            font:getComputedStyle(document.body).lineHeight};
                    }""")
                    errors = []
                    if observed["overflow"]:errors.append("horizontal scrollbar")
                    if observed["font"] != "20px":errors.append(f"body baseline {observed['font']}")
                    for x in observed["inputs"]:
                        if x["h"] != 40:errors.append(f"input/control {x}")
                    for x in observed["checks"]:
                        if x["h"] != 18 or x["w"] != 18:errors.append(f"checkbox {x}")
                    for x in observed["buttons"]:
                        if x["h"] != 40:errors.append(f"button {x}")
                    results.append({"width":width,"language":lang,"theme":theme,"page":tab,"errors":errors})
                    if width == 1440 and lang == "ru" and theme == "light" and tab in ("tenders", "economics"):
                        page.locator("#toast").evaluate("e=>e.style.display='none'")
                        page.screenshot(path=str(OUTPUT / f"desktop_{tab}.png"), full_page=True)
                    if width == 390 and lang == "en" and theme == "dark" and tab in ("criteria", "economics"):
                        page.wait_for_timeout(260)
                        page.locator("#toast").evaluate("e=>e.style.display='none'")
                        page.screenshot(path=str(OUTPUT / f"mobile_{tab}.png"), full_page=True)
        page.close()
    browser.close()

report = OUTPUT / "report.json"
report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
failed = [r for r in results if r["errors"]]
print(f"UI cases: {len(results)}, failed: {len(failed)}")
for result in failed[:15]:print(result)
if failed:raise SystemExit(1)
