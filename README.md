# Discord Shop Fetcher

Fetches all collectible items from the Discord shop API - avatar decorations, profile effects, and nameplates with bilingual names, prices, color variants, and preview images.

## Setup

```bash
pip install requests python-dotenv
```

Create a `.env` file:
```
DISCORD_TOKEN=your_user_token
PROXY=host:port@user:pass  # optional, SOCKS5
# SECOND_LOCALE=ru
```

The token is your Discord user authorization token (from browser DevTools > Network > any request > `Authorization` header).

## Usage

```bash
python main.py                # English + Russian (default)
python main.py -l ja          # English + Japanese
python main.py -l de          # English + German
python main.py --no-previews  # skip image downloads
```

The second locale can also be set via `SECOND_LOCALE` in `.env`.

Output:
- `discord_shop.json` - all items with names, prices, variants, and preview URLs
- `previews/` - downloaded preview images (PNG/GIF/WebP)

## Output format

```json
{
  "sku_id": "1234567890",
  "name_en": "Cyber Punk",
  "name_ru": "Киберпанк",
  "type": "AVATAR_DECORATION",
  "category_en": "Anime",
  "category_ru": "Аниме",
  "price": 7.99,
  "price_nitro": 5.99,
  "currency": "eur",
  "has_variants": true,
  "variant_count": 3,
  "variants": [
    {
      "sku_id": "...",
      "name_en": "Cyber Punk Blue",
      "name_ru": "Киберпанк синий",
      "preview_url": "https://..."
    }
  ],
  "preview_url": "https://...",
  "preview_animated_url": "https://..."
}
```

The `name_ru` / `category_ru` keys change based on the chosen locale (e.g. `name_ja`, `category_de`).

Item types: `AVATAR_DECORATION`, `PROFILE_EFFECT`, `NAMEPLATE`.

Prices are returned in the currency tied to your IP or account's linked card.

## How it works

1. Hits Discord's `/api/v9/collectibles-categories/v2` endpoint twice - once per locale
2. Merges the responses to get bilingual names
3. Extracts prices, preview URLs, and color variant relationships
4. Downloads all preview images locally
5. Handles rate limits (429) with automatic retry
