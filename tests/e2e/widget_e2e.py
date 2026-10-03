"""Browser test of the real embed flow. Needs the API on :8000 and the demo site on :8080
(see docs/GETTING_STARTED.md). Run:  python tests/e2e/widget_e2e.py"""

import sys

from playwright.sync_api import sync_playwright

ALLOWED = "http://localhost:8080/"
BLOCKED = "http://localhost:8081/"


def run() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(ALLOWED)
        launcher = page.locator("ai-sales-concierge >> .launch")
        launcher.click()
        notice = page.locator("ai-sales-concierge >> .notice").inner_text()
        if "AI assistant" not in notice:
            failures.append("AI notice not shown")
        page.locator("ai-sales-concierge >> .cta").click()
        page.locator("ai-sales-concierge >> input").fill("Do you have 2-bed flats?")
        page.locator("ai-sales-concierge >> .send").click()
        reply = page.locator("ai-sales-concierge >> .msg.agent").nth(1)
        reply.wait_for(timeout=5000)
        if "Do you have 2-bed flats?" not in reply.inner_text():
            failures.append(f"unexpected reply: {reply.inner_text()!r}")
        print("allowed site OK:", reply.inner_text()[:70])

        page2 = browser.new_page()
        page2.goto(BLOCKED)
        page2.locator("ai-sales-concierge >> .launch").click()
        page2.locator("ai-sales-concierge >> .cta").click()
        err = page2.locator("ai-sales-concierge >> .msg.error")
        err.wait_for(timeout=5000)
        if "not approved" not in err.inner_text():
            failures.append(f"blocked site message wrong: {err.inner_text()!r}")
        print("blocked site OK:", err.inner_text())
        browser.close()
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
