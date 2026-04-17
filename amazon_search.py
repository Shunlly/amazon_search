import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def parse_args():
    parser = argparse.ArgumentParser(
        description="使用 Playwright 抓取亚马逊搜索结果。"
    )
    parser.add_argument("-k", "--keyword", required=True, help="搜索关键词")
    parser.add_argument("-p", "--pages", type=int, default=1, help="抓取页数，默认 1")
    parser.add_argument(
        "--domain",
        default="www.amazon.com",
        help="亚马逊站点域名，默认 www.amazon.com",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output/amazon-search.json",
        help="输出 JSON 文件路径",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="启用无头模式，默认开启",
    )
    parser.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="关闭无头模式，显示浏览器窗口",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=100,
        dest="slow_mo",
        help="浏览器每步延迟毫秒数，默认 100",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45000,
        help="页面超时时间，单位毫秒，默认 45000",
    )
    parser.add_argument("--proxy", default="", help="代理地址，例如 http://127.0.0.1:7890")
    parser.add_argument(
        "--storage-state",
        default="",
        dest="storage_state",
        help="Playwright storage state 文件路径",
    )
    parser.add_argument(
        "--debug-dir",
        default="output/debug",
        dest="debug_dir",
        help="调试文件目录，默认 output/debug",
    )
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages 必须大于等于 1")
    return args


def build_search_url(domain, keyword, page_number):
    query = urlencode({"k": keyword, "page": page_number, "ref": f"sr_pg_{page_number}"})
    return f"https://{domain}/s?{query}"


def sanitize_filename(value):
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-zA-Z0-9-_]+", "-", value))


def normalize_domain(domain):
    return re.sub(r"^https?://", "", domain.strip().lower()).split("/", 1)[0]


def format_amazon_label(domain):
    host = normalize_domain(domain).removeprefix("www.")
    if host.startswith("amazon."):
        return f"Amazon.{host.split('amazon.', 1)[1]}"
    return host


def dismiss_startup_overlays(page, target_domain):
    page.mouse.move(5, 5)
    try:
        page.keyboard.press("Escape")
    except PlaywrightTimeoutError:
        pass

    popup_title = page.get_by_text("Choosing your Amazon website", exact=False)
    try:
        popup_title.wait_for(state="visible", timeout=2500)
    except PlaywrightTimeoutError:
        return

    target_label = format_amazon_label(target_domain)
    action_name = ""
    candidate_buttons = []

    if target_label.lower() == "amazon.com":
        candidate_buttons.append(
            ("Go to Amazon.com", page.get_by_role("button", name=re.compile(r"Go to Amazon\.com", re.IGNORECASE)))
        )
    else:
        candidate_buttons.append(
            (
                f"Stay on {target_label}",
                page.get_by_role(
                    "button",
                    name=re.compile(rf"Stay on\s+{re.escape(target_label)}", re.IGNORECASE),
                ),
            )
        )
        if target_label.lower() == "amazon.sg":
            candidate_buttons.append(
                ("Go to Amazon.com", page.get_by_role("button", name=re.compile(r"Go to Amazon\.com", re.IGNORECASE)))
            )

    for button_name, locator in candidate_buttons:
        if locator.count() > 0 and locator.first.is_visible():
            locator.first.click()
            action_name = button_name
            break

    if not action_name:
        close_button = page.locator(
            'button[aria-label="Close"], button[data-action="a-popover-close"], .a-popover-header button'
        )
        if close_button.count() > 0 and close_button.first.is_visible():
            close_button.first.click()
            action_name = "关闭弹框"
        else:
            page.keyboard.press("Escape")
            action_name = "按 Esc 关闭弹框"

    page.wait_for_timeout(500)
    print(f"检测到站点选择弹框，已执行: {action_name}")


def detect_block(page):
    title = page.title()
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except PlaywrightTimeoutError:
        body_text = ""
    content = f"{title}\n{body_text}"

    if re.search(r"captcha|Enter the characters you see below", content, re.IGNORECASE):
        return "检测到验证码页面"

    if "Sorry, we just need to make sure" in content:
        return "检测到风控校验页面"

    return ""


def save_debug_artifacts(page, debug_dir, keyword, page_number):
    debug_path = Path(debug_dir)
    debug_path.mkdir(parents=True, exist_ok=True)
    base_name = f"{sanitize_filename(keyword)}-page-{page_number}"
    screenshot_path = debug_path / f"{base_name}.png"
    html_path = debug_path / f"{base_name}.html"
    page.screenshot(path=str(screenshot_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")
    return {"screenshot_path": str(screenshot_path), "html_path": str(html_path)}


def collect_products(page, page_number):
    cards = page.locator('[data-component-type="s-search-result"][data-asin]')
    count = cards.count()
    items = []

    for index in range(count):
        card = cards.nth(index)
        item = card.evaluate(
            """
            (node, meta) => {
              const text = (selector) => node.querySelector(selector)?.textContent?.trim() ?? "";
              const attr = (selector, name) => node.querySelector(selector)?.getAttribute(name)?.trim() ?? "";

              const asin = node.getAttribute("data-asin")?.trim() ?? "";
              const title = text("h2 a span") || text("h2 span");
              const productLink =
                node.querySelector('a[href*="/dp/"]') ||
                node.querySelector('a[href*="/gp/product/"]') ||
                node.querySelector("h2 a");
              const relativeUrl = productLink?.getAttribute("href")?.trim() ?? "";
              const productUrl = relativeUrl
                ? new URL(relativeUrl, location.origin).toString()
                : asin
                  ? new URL(`/dp/${asin}`, location.origin).toString()
                  : "";
              const image = attr("img.s-image", "src");
              const price = text(".a-price .a-offscreen");
              const originalPrice = text(".a-price.a-text-price .a-offscreen");
              const ratingText =
                attr('[aria-label*="out of 5 stars"]', "aria-label") ||
                text(".a-icon-alt") ||
                "";
              const reviewCount =
                text('a[href*="#customerReviews"] span') ||
                text('a[href*="customerReviews"] span') ||
                "";
              const badge = text(".a-badge-text");
              const boughtText = text('span[aria-label*="bought in past month"]') || "";
              const shipping = text('[data-cy="delivery-recipe"]') || text(".a-color-base.a-text-bold");
              const sponsored =
                node.innerText.includes("Sponsored") ||
                !!node.querySelector('[aria-label="Sponsored"]') ||
                !!node.querySelector('span[data-component-type="s-sponsored-label-marker"]');
              const prime =
                !!node.querySelector('[aria-label="Amazon Prime"]') ||
                !!node.querySelector(".a-icon-prime");

              const ratingMatch = ratingText.match(/([0-9.]+)/);

              return {
                page: meta.pageNumber,
                position: meta.position,
                asin,
                title,
                productUrl,
                image,
                price,
                originalPrice,
                rating: ratingMatch ? ratingMatch[1] : "",
                ratingText,
                reviewCount,
                badge,
                boughtText,
                shipping,
                sponsored,
                prime
              };
            }
            """,
            {"pageNumber": page_number, "position": index + 1},
        )
        if item.get("asin") and item.get("title"):
            items.append(item)

    return items


def write_json(output_path, payload):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    args = parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow_mo,
            proxy={"server": args.proxy} if args.proxy else None,
        )
        context = browser.new_context(
            storage_state=args.storage_state or None,
            viewport={"width": 1440, "height": 1200},
            locale="en-US",
            timezone_id="America/Los_Angeles",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(args.timeout)

        all_items = []
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        try:
            for current_page in range(1, args.pages + 1):
                target_url = build_search_url(args.domain, args.keyword, current_page)
                print(f"打开第 {current_page} 页: {target_url}")

                page.goto(target_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=args.timeout)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1500)
                dismiss_startup_overlays(page, args.domain)

                blocked_reason = detect_block(page)
                if blocked_reason:
                    artifacts = save_debug_artifacts(
                        page, args.debug_dir, args.keyword, current_page
                    )
                    raise RuntimeError(
                        f"{blocked_reason}，已输出调试文件: {artifacts['screenshot_path']}"
                    )

                results = page.locator('[data-component-type="s-search-result"][data-asin]')
                results.first.wait_for(state="visible", timeout=args.timeout)
                page.wait_for_timeout(800)

                items = collect_products(page, current_page)
                print(f"第 {current_page} 页抓取到 {len(items)} 条商品")

                if not items:
                    artifacts = save_debug_artifacts(
                        page, args.debug_dir, args.keyword, current_page
                    )
                    raise RuntimeError(
                        f"未抓到商品数据，已输出调试文件: {artifacts['screenshot_path']}"
                    )

                all_items.extend(items)

            payload = {
                "keyword": args.keyword,
                "domain": args.domain,
                "pages": args.pages,
                "total": len(all_items),
                "startedAt": started_at,
                "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "items": all_items,
            }
            write_json(args.output, payload)
            print(f"抓取完成，共 {payload['total']} 条，已写入 {args.output}")
        except PlaywrightTimeoutError as error:
            raise RuntimeError(f"页面等待超时: {error}") from error
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\n抓取失败:", file=sys.stderr)
        print(str(error), file=sys.stderr)
        print("\n排查建议:", file=sys.stderr)
        print("1. 先不要加 --headless，用可视化模式观察页面。", file=sys.stderr)
        print("2. 如遇验证码，考虑使用更稳定的网络环境或登录后的 storage state。", file=sys.stderr)
        print("3. 如站点不是美国站，改用对应 --domain，例如 www.amazon.co.jp。", file=sys.stderr)
        sys.exit(1)
