"""
Discord Shop Fetcher

Fetches all collectible items from Discord's shop API:
- Avatar decorations, profile effects, nameplates
- Bilingual names (any two locales)
- Prices in the account's currency
- Color variant info
- Preview image downloads
"""

import argparse
import requests
import json
import os
import time
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

ITEM_TYPES = {
    0: "AVATAR_DECORATION",
    1: "PROFILE_EFFECT",
    2: "NAMEPLATE",
}

OUTPUT_DIR = Path(__file__).parent
PREVIEWS_DIR = OUTPUT_DIR / "previews"

class DiscordShopFetcher:

    BASE_URL = "https://discord.com/api/v9"

    def __init__(self, token: str, proxy: str = None):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/147.0",
        })

        if proxy:
            if "@" in proxy:
                host_port, auth = proxy.split("@")
                user, password = auth.split(":")
                proxy_url = f"socks5://{user}:{password}@{host_port}"
            else:
                proxy_url = f"socks5://{proxy}"
            self.session.proxies = {"http": proxy_url, "https": proxy_url}

    def _request(self, endpoint: str, **kwargs) -> Optional[dict]:
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = self.session.get(url, **kwargs)
            if resp.status_code == 429:
                wait = resp.json().get("retry_after", 5)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                return self._request(endpoint, **kwargs)
            if resp.status_code == 200:
                return resp.json()
            print(f"  Error {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            print(f"  Request failed: {e}")
        return None

    def fetch_categories(self, locale: str) -> Optional[dict]:
        return self._request(
            "collectibles-categories/v2",
            params={"include_bundles": "true", "variants_return_style": "2", "skip_num_categories": "0"},
            headers={"X-Discord-Locale": locale},
        )

    def _extract_preview(self, item: dict) -> tuple[Optional[str], Optional[str]]:
        """Return (static_url, animated_url) for an item."""
        t = item.get("type")
        assets = item.get("assets", {})

        if t == 0:  # Avatar decoration
            static = assets.get("static_image_url")
            if not static:
                asset_id = item.get("asset")
                if asset_id:
                    static = f"https://cdn.discordapp.com/avatar-decoration-presets/{asset_id}.png"
            return static, assets.get("animated_image_url")

        if t == 1:  # Profile effect
            src = item.get("thumbnailPreviewSrc") or item.get("reducedMotionSrc")
            if not src:
                effects = item.get("effects", [])
                if effects:
                    src = effects[0].get("src")
            return src, None

        if t == 2:  # Nameplate
            return assets.get("static_image_url"), assets.get("animated_image_url")

        return None, None

    def _extract_prices(self, prices: dict) -> dict:
        """Extract regular and Nitro prices from a product's price object."""
        result = {"price": None, "price_nitro": None, "currency": None}
        for key, field in [("0", "price"), ("4", "price_nitro")]:
            if key not in prices:
                continue
            for p in prices[key].get("country_prices", {}).get("prices", []):
                if p.get("currency") == "discord_orb":
                    continue
                amount = p.get("amount", 0)
                exponent = p.get("exponent", 2)
                result[field] = amount / (10 ** exponent)
                if not result["currency"]:
                    result["currency"] = p.get("currency")
        return result

    def _parse_locale(self, data: dict) -> tuple[dict, dict]:
        """Parse one locale's response into sku->name and sku->category maps."""
        names = {}
        categories = {}

        for category in data.get("categories", []):
            cat_name = category.get("name")
            for product in category.get("products", []):
                items = list(product.get("items", []))
                variant_names = {}

                # Standalone products keep items in variants[], not items[]
                if not items:
                    for variant in product.get("variants", []):
                        vname = variant.get("name")
                        for vi in variant.get("items", []):
                            sku = vi.get("sku_id")
                            if sku:
                                variant_names[sku] = vname
                            items.append(vi)

                for item in items:
                    sku = item.get("sku_id")
                    if not sku:
                        continue
                    name = variant_names.get(sku)
                    if not name:
                        name = item.get("title") or product.get("name")
                    names[sku] = name
                    categories[sku] = cat_name

        return names, categories

    def extract_items(self, data_primary: dict, data_secondary: dict, secondary_locale: str = "ru") -> list[dict]:
        """Build the item list by merging two locale responses."""
        names_en, cats_en = self._parse_locale(data_primary)
        names_sec, cats_sec = self._parse_locale(data_secondary)
        lang = secondary_locale.split("-")[0]  # "pt-BR" -> "pt"

        # We need the full item data and product prices from the primary locale
        sku_items = {}      # sku -> raw item dict
        sku_prices = {}     # sku -> extracted price dict
        sku_product = {}    # sku -> product_sku (for grouping variants)
        product_skus = {}   # product_sku -> [item_skus]

        for category in data_primary.get("categories", []):
            for product in category.get("products", []):
                items = list(product.get("items", []))
                if not items:
                    for variant in product.get("variants", []):
                        items.extend(variant.get("items", []))

                prices = self._extract_prices(product.get("prices", {}))
                prod_sku = product.get("sku_id")

                for item in items:
                    sku = item.get("sku_id")
                    if not sku:
                        continue
                    sku_items[sku] = item
                    sku_prices[sku] = prices
                    sku_product[sku] = prod_sku
                    product_skus.setdefault(prod_sku, []).append(sku)

        result = []
        for sku, item in sku_items.items():
            name_en = names_en.get(sku)
            if not name_en:
                continue

            item_type = item.get("type")
            static_url, animated_url = self._extract_preview(item)
            prices = sku_prices[sku]

            # Build variant list (same type, no bundles)
            prod_sku = sku_product[sku]
            sibling_skus = product_skus.get(prod_sku, [])
            variants = []
            if len(sibling_skus) > 1:
                for vs in sibling_skus:
                    vi = sku_items.get(vs)
                    if not vi or vi.get("type") != item_type:
                        continue
                    vn = names_en.get(vs, "")
                    if "Bundle" in vn:
                        continue
                    v_static, v_animated = self._extract_preview(vi)
                    variants.append({
                        "sku_id": vs,
                        "name_en": vn,
                        f"name_{lang}": names_sec.get(vs),
                        "preview_url": v_static,
                        "preview_animated_url": v_animated,
                    })

            has_variants = len(variants) > 1

            result.append({
                "sku_id": sku,
                "name_en": name_en,
                f"name_{lang}": names_sec.get(sku),
                "type": ITEM_TYPES.get(item_type, f"TYPE_{item_type}"),
                "category_en": cats_en.get(sku),
                f"category_{lang}": cats_sec.get(sku),
                **prices,
                "has_variants": has_variants,
                "variant_count": len(variants) if has_variants else 0,
                "variants": variants if has_variants else None,
                "preview_url": static_url,
                "preview_animated_url": animated_url,
            })

        return result

    def download_previews(self, items: list[dict]):
        """Download preview images for all items and their variants."""
        PREVIEWS_DIR.mkdir(exist_ok=True)
        count = 0

        def _dl(url, sku):
            nonlocal count
            if not url:
                return None
            ext = "gif" if ".gif" in url else "webp" if ".webp" in url else "png"
            path = PREVIEWS_DIR / f"{sku}.{ext}"
            if path.exists():
                return str(path)
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    path.write_bytes(resp.content)
                    count += 1
                    return str(path)
            except Exception as e:
                print(f"  Failed: {sku} - {e}")
            return None

        for item in items:
            item["preview_local"] = _dl(item.get("preview_url"), item["sku_id"])
            if item.get("variants"):
                for v in item["variants"]:
                    v["preview_local"] = _dl(v.get("preview_url"), v["sku_id"])
            time.sleep(0.1)

        print(f"  Downloaded {count} images to {PREVIEWS_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Fetch Discord shop collectibles")
    parser.add_argument("-l", "--locale", default=os.getenv("SECOND_LOCALE", "ru"),
                        help="Second locale for bilingual names (default: ru). Examples: ru, ja, de, pt-BR, zh-CN")
    parser.add_argument("--no-previews", action="store_true", help="Skip downloading preview images")
    args = parser.parse_args()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        token = input("Enter Discord token: ").strip()
        if not token:
            print("No token provided.")
            return

    proxy = os.getenv("PROXY")
    locale = args.locale
    fetcher = DiscordShopFetcher(token, proxy=proxy)

    print("Fetching EN locale...")
    data_en = fetcher.fetch_categories("en-US")
    if not data_en:
        return

    print(f"Fetching {locale} locale...")
    data_secondary = fetcher.fetch_categories(locale)
    if not data_secondary:
        return

    print("Extracting items...")
    items = fetcher.extract_items(data_en, data_secondary, locale)
    print(f"  {len(items)} items found")

    if not args.no_previews:
        print("Downloading previews...")
        fetcher.download_previews(items)

    # Save
    out = OUTPUT_DIR / "discord_shop.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"Saved to {out}")

    # Summary
    types = {}
    for item in items:
        t = item["type"]
        types[t] = types.get(t, 0) + 1
    for t, n in sorted(types.items()):
        print(f"  {t}: {n}")
if __name__ == "__main__":
    main()
