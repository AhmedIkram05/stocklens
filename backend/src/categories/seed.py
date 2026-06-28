"""
Seed data for the ``spending_categories`` table.

Each entry includes a name, description, a list of merchant keywords used
for regex matching, and a list of associated stock tickers relevant to that
spending category (for investment analysis).
"""

from __future__ import annotations

from typing import Any

SEED_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "Groceries",
        "description": "Supermarkets, grocery stores, and food markets",
        "merchant_keywords": [
            "tesco", "sainsbury", "asda", "morrisons", "waitrose",
            "aldi", "lidl", "co-op", "iceland", "m&s food",
            "marks and spencer", "farmfoods", "food warehouse",
            "whole foods", "trader joe", "kroger", "costco",
            "walmart", "publix", "wegmans",
        ],
        "associated_tickers": ["TSCO.L", "SBRY.L", "OCDO.L", "KR", "COST", "WMT"],
    },
    {
        "name": "Dining Out",
        "description": "Restaurants, cafes, fast food, and takeaway",
        "merchant_keywords": [
            "restaurant", "cafe", "café", "pizza", "burger", "sushi",
            "mcdonald", "kfc", "subway", "starbucks", "costa",
            "pret a manger", "greggs", "nando", "wagamama",
            "domino", "pizza hut", "taco bell", "five guys",
            "dishoom", "zizzi", "ask italian", "bella italia",
        ],
        "associated_tickers": ["MCD", "SBUX", "YUM", "DPZ", "QSR", "CMG", "DNKEY"],
    },
    {
        "name": "Transportation",
        "description": "Public transport, fuel, parking, and ride-sharing",
        "merchant_keywords": [
            "tfl", "transport", "uber", "lyft", "bolt", "trainline",
            "national rail", "bus", "tube", "underground",
            "shell", "bp", "esso", "texaco", "petrol", "parking",
            "euston", "paddington", "king's cross", "gatwick",
            "heathrow", "easyjet", "ryanair", "virgin",
        ],
        "associated_tickers": ["UBER", "LYFT", "SHEL", "BP", "RYAAY", "EZJ.L", "TRAIN"],
    },
    {
        "name": "Shopping",
        "description": "Retail, clothing, electronics, and general merchandise",
        "merchant_keywords": [
            "amazon", "ebay", "next", "zara", "h&m", "uniqlo",
            "argos", "john lewis", "debenhams", "asos",
            "best buy", "currys", "apple store", "ikea",
            "hema", "claire", "boots", "superdrug",
            "primark", "matalan", "tk maxx", "home goods",
        ],
        "associated_tickers": ["AMZN", "EBAY", "NXT.L", "WMT", "TGT", "HD", "LOW", "BBB.L"],
    },
    {
        "name": "Entertainment",
        "description": "Cinema, streaming, concerts, and leisure activities",
        "merchant_keywords": [
            "netflix", "spotify", "disney", "hulu", "prime video",
            "odeon", "cineworld", "vue", "showcase",
            "national theatre", "broadway", "ticketmaster",
            "sky", "now tv", "youtube premium", "apple music",
            "hbo", "paramount", "peacock", "event cinemas",
        ],
        "associated_tickers": ["NFLX", "SPOT", "DIS", "WBD", "PARA", "CMCSA", "SONY", "VIX"],
    },
    {
        "name": "Health & Pharmacy",
        "description": "Pharmacies, health services, and wellness",
        "merchant_keywords": [
            "boots", "superdrug", "pharmacy", "lloyds pharmacy",
            "chemist", "nhs", "hospital", "dentist", "optician",
            "specsavers", "vision express", "vitality",
            "holland and barrett", "vitamins", "gym",
            "pure gym", "fitness first", "nuffield health",
        ],
        "associated_tickers": ["WBA", "CVS", "EL", "NVO", "LLOY.L", "PFE"],
    },
    {
        "name": "Housing & Utilities",
        "description": "Rent, mortgage, utilities, and home services",
        "merchant_keywords": [
            "british gas", "eon", "edf", "ovo", "sse", "npower",
            "water bill", "council tax", "housing", "rent",
            "thames water", "severn trent", "virgin media",
            "bt", "sky", "ee", "vodafone", "three",
            "landlord", "tenancy", "letting agent",
        ],
        "associated_tickers": ["CNA.L", "NG.L", "SSE.L", "BT-A.L", "VOD.L", "VZ", "T"],
    },
    {
        "name": "Technology & Software",
        "description": "Software subscriptions, cloud services, and tech products",
        "merchant_keywords": [
            "microsoft", "google", "apple", "adobe", "salesforce",
            "aws", "azure", "digitalocean", "heroku", "github",
            "slack", "zoom", "notion", "figma", "canva",
            "jetbrains", "vscode", "datadog", "cloudflare",
            "mongo", "new relic", "segment",
        ],
        "associated_tickers": [
            "MSFT", "GOOGL", "AAPL", "ADBE", "CRM", "ORCL", "NET", "DDOG", "MDB",
        ],
    },
    {
        "name": "Travel & Accommodation",
        "description": "Hotels, flights, holiday rentals, and travel services",
        "merchant_keywords": [
            "booking.com", "expedia", "airbnb", "hotels.com",
            "tripadvisor", "skyscanner", "kayak", "trivago",
            "marriott", "hilton", "ihg", "accor", "premier inn",
            "travelodge", "holiday inn", "tui", "thomas cook",
            "jet2", "british airways", "emirates", "virgin atlantic",
        ],
        "associated_tickers": ["BKNG", "EXPE", "ABNB", "HLT", "MAR", "IHG", "TUI.L", "IAG.L"],
    },
    {
        "name": "Financial Services",
        "description": "Banking, insurance, investments, and financial planning",
        "merchant_keywords": [
            "barclays", "hsbc", "lloyds", "natwest", "nationwide",
            "monzo", "starling", "revolut", "wise", "paypal",
            "stripe", "transferwise", "advisers", "pension",
            "vanguard", "fidelity", "blackrock", "schwab",
            "aviva", "legal and general", "prudential",
        ],
        "associated_tickers": [
            "BARC.L", "HSBA.L", "LLOY.L", "NWG.L", "PYPL", "V", "MA", "BLK", "SCHW",
        ],
    },
]


def get_seed_categories() -> list[dict[str, Any]]:
    """Return a copy of the seed categories."""
    return [dict(c) for c in SEED_CATEGORIES]


CATEGORY_NAMES: list[str] = [c["name"] for c in SEED_CATEGORIES]
