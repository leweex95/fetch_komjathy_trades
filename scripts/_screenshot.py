import sys
from playwright.sync_api import sync_playwright
import os

target = sys.argv[1] if len(sys.argv) > 1 else "chart.html"
out = sys.argv[2] if len(sys.argv) > 2 else "_chart_screenshot.png"
path = "file:///" + os.path.abspath(target).replace("\\", "/")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1700, "height": 1000})
    page.goto(path)
    page.wait_for_timeout(1500)
    page.screenshot(path=out, full_page=True)
    browser.close()
print("done:", out)
