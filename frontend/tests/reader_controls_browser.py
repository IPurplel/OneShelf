"""Check that EPUB reader controls stay reachable at phone, tablet, and desktop widths."""
import argparse
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from layout_browser import fixture


def epub():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("META-INF/container.xml",
                         '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        archive.writestr("OEBPS/content.opf",
                         '<package><metadata><title>Reader controls</title></metadata><manifest>'
                         '<item id="c1" href="chapter.xhtml"/></manifest><spine><itemref idref="c1"/>'
                         '</spine></package>')
        archive.writestr("OEBPS/chapter.xhtml", "<html><body><p>A readable chapter.</p></body></html>")
    return data.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--screenshots", default="/tmp/oneshelf-reader-controls")
    args = parser.parse_args()
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    book = epub()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language in ("en", "ar"):
            for width in (390, 768, 1440):
                page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
                page.add_init_script(f"try {{ localStorage.setItem('oneshelf.language', '{language}') }} catch {{}}")

                def route(request):
                    path = urlparse(request.request.url).path
                    if path == "/api/reader/units/u0/context":
                        return request.fulfill(json={"work_id": "w0", "track_id": "t0", "formats": ["epub"]})
                    if path == "/api/reader/units/u0/file":
                        return request.fulfill(content_type="application/epub+zip", body=book)
                    if path == "/api/reader/units/u0/marks":
                        return request.fulfill(json={"bookmarks": [], "highlights": []})
                    return fixture(request, 3)

                page.route(args.url + "/api/**", route)
                page.goto(args.url + "/read/u0?work=w0&track=t0")
                page.get_by_role("status").filter(has_text="1").wait_for()
                result = page.evaluate("""() => {
                    const viewport = innerWidth;
                    const controls = [...document.querySelectorAll('.reader__bar--top .reader__button, '
                      + '.reader__bar--bottom .reader__button, .reader__bar--bottom [role=status]')];
                    const positions = controls.map(el => {
                      const r = el.getBoundingClientRect();
                      const x = Math.max(0, Math.min(viewport - 1, r.left + r.width / 2));
                      const y = Math.max(0, Math.min(innerHeight - 1, r.top + r.height / 2));
                      return {name: el.textContent.trim(), left: r.left, right: r.right,
                        top: r.top, bottom: r.bottom, visible: r.width > 0 && r.height > 0,
                        topElement: document.elementFromPoint(x, y), self: el};
                    });
                    return {overflow: document.documentElement.scrollWidth - viewport,
                      controls: positions.map(({name,left,right,top,bottom,visible,topElement,self}) => ({
                        name,left,right,top,bottom,visible,
                        reachable: self === topElement || self.contains(topElement)
                      }))};
                }""")
                page.screenshot(path=str(out / f"{language}-{width}-reader.png"), full_page=True)
                assert result["overflow"] <= 1, f"{language} {width}: viewport overflow {result}"
                assert result["controls"], f"{language} {width}: no reader controls"
                for control in result["controls"]:
                    assert control["visible"] and control["left"] >= 0 and control["right"] <= width + 1, (
                        f"{language} {width}: clipped {control}")
                    assert control["top"] >= 0 and control["bottom"] <= 844, (
                        f"{language} {width}: outside viewport {control}")
                    assert control["reachable"], f"{language} {width}: covered {control}"
                print("PASS", language, width, json.dumps({"controls": len(result["controls"]),
                      "overflow": result["overflow"]}), flush=True)
                page.close()
        browser.close()


if __name__ == "__main__":
    main()
