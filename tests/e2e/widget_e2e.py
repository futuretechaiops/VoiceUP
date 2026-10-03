"""Browser test of the real embed flow. Needs the API on :8000 and the demo site on :8080
(see docs/GETTING_STARTED.md). Run:  python tests/e2e/widget_e2e.py"""

import os
import sys

from playwright.sync_api import sync_playwright

ALLOWED = "http://localhost:8080/"
BLOCKED = "http://localhost:8081/"


def run() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_EXECUTABLE_PATH") or None)
        page = browser.new_page()
        page.goto(ALLOWED)
        launcher = page.locator("ai-sales-concierge >> .launch")
        launcher.click()
        notice = page.locator("ai-sales-concierge >> .notice").inner_text()
        if "AI assistant" not in notice:
            failures.append("AI notice not shown")
        page.locator("ai-sales-concierge >> .cta").click()
        page.locator("ai-sales-concierge >> input[name=text]").fill("What are your tenant fees?")
        page.locator("ai-sales-concierge >> .send").click()
        reply = page.locator("ai-sales-concierge >> .msg.agent").nth(1)
        reply.wait_for(timeout=15000)
        text = reply.inner_text()
        if "holding deposit" not in text:
            failures.append(f"answer not grounded in the website: {text!r}")
        print("answer OK:", text[:90].replace("\n", " "))
        source = page.locator("ai-sales-concierge >> .sources a").first
        source.wait_for(timeout=5000)
        if not source.get_attribute("href", timeout=2000).endswith("/lettings"):
            failures.append("source link missing or wrong")

        # call-back form: name, number and email go to the team
        page.locator("ai-sales-concierge >> .callback").click()
        page.locator("ai-sales-concierge >> input[name=name]").fill("Jane Visitor")
        page.locator("ai-sales-concierge >> input[name=phone]").fill("07700 900123")
        page.locator("ai-sales-concierge >> input[name=email]").fill("jane@example.com")
        page.locator("ai-sales-concierge >> .go").click()
        page.locator("ai-sales-concierge >> .err").wait_for(state="attached")
        if "tick the box" not in page.locator("ai-sales-concierge >> .err").inner_text():
            failures.append("consent was not enforced")
        page.locator("ai-sales-concierge >> input[name=consent]").check()
        page.locator("ai-sales-concierge >> .go").click()
        thanks = page.locator("ai-sales-concierge >> .msg.agent", has_text="Thank you")
        thanks.wait_for(timeout=10000)
        print("call-back form OK")

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
