# Amazon Playwright Scraper

一个基于 Python Playwright 的亚马逊搜索结果抓取脚本，支持搜索关键词、抓取页数等命令行选项，默认使用无头浏览器并输出 JSON。
脚本会自动处理常见的站点选择弹框，例如 `Choosing your Amazon website`。

## 安装

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

## 用法

```bash
python3 scripts/amazon_search.py --keyword "wireless mouse" --pages 2
```

## 常用参数

- `--keyword` / `-k`：搜索关键词，必填
- `--pages` / `-p`：抓取页数，默认 `1`
- `--domain`：亚马逊站点域名，默认 `www.amazon.com`
- `--output` / `-o`：输出 JSON 文件路径，默认 `output/amazon-search.json`
- `--headless`：启用无头模式，默认开启
- `--headed`：关闭无头模式，显示浏览器窗口，适合调试
- `--slow-mo`：浏览器每步延迟毫秒数，默认 `100`
- `--timeout`：页面超时时间，默认 `45000`
- `--proxy`：代理地址
- `--storage-state`：传入已登录状态文件
- `--debug-dir`：调试文件目录，默认 `output/debug`

## 示例

```bash
python3 scripts/amazon_search.py -k "usb c hub" -p 3
python3 scripts/amazon_search.py -k "usb c hub" -p 1 --headed
python3 scripts/amazon_search.py -k "mechanical keyboard" --domain www.amazon.co.jp
```

## 输出字段

每条商品默认包含这些字段：

- `asin`
- `title`
- `productUrl`
- `image`
- `price`
- `originalPrice`
- `rating`
- `ratingText`
- `reviewCount`
- `badge`
- `boughtText`
- `shipping`
- `sponsored`
- `prime`

## 注意

亚马逊风控较严格，若出现验证码或空结果，脚本会把截图和 HTML 输出到 `output/debug/` 方便排查。
