"""
SeLoger.com scraper — largest French real estate portal.
Uses their internal JSON API (__NEXT_DATA__) embedded in HTML pages.
"""
import requests
import json
from typing import Optional
from .base import Listing, HEADERS, extract_int, extract_number


BASE_URL = "https://www.seloger.com"

TRANSACTION_MAP = {
    "rent": "2",
    "sale": "1",
}

PROPERTY_MAP = {
    "apartment": "1",
    "house": "2",
    "studio": "1",
    "any": "",
}


def _build_url(
    listing_type: str,
    location: str,
    property_type: str,
    max_price: Optional[int],
    min_surface: Optional[int],
    rooms: Optional[int],
) -> str:
    transaction = TRANSACTION_MAP.get(listing_type, "2")
    prop_id = PROPERTY_MAP.get(property_type, "")

    params = [
        f"ci={_city_code(location)}",
        f"idtypebien={prop_id}" if prop_id else "",
        f"idtransaction={transaction}",
        f"pxmax={max_price}" if max_price else "",
        f"surfacemin={min_surface}" if min_surface else "",
        f"nb_pieces={rooms}" if rooms else "",
    ]
    params = [p for p in params if p]

    return f"{BASE_URL}/list.htm?{('&'.join(params))}"


def _city_code(location: str) -> str:
    city_codes = {
        "paris": "75056",
        "lyon": "69123",
        "marseille": "13055",
        "bordeaux": "33063",
        "toulouse": "31555",
        "nice": "06088",
        "nantes": "44109",
        "strasbourg": "67482",
        "montpellier": "34172",
        "lille": "59350",
        "rennes": "35238",
        "grenoble": "38185",
    }
    return city_codes.get(location.lower(), "75056")


def search(
    listing_type: str = "rent",
    location: str = "paris",
    property_type: str = "any",
    max_price: Optional[int] = None,
    min_surface: Optional[int] = None,
    rooms: Optional[int] = None,
    max_results: int = 10,
) -> list[Listing]:
    url = _build_url(listing_type, location, property_type, max_price, min_surface, rooms)
    results = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()

        data = _extract_next_data(resp.text)
        if data:
            listings_raw = _get_listings_from_json(data)
            for raw in listings_raw[:max_results]:
                listing = _parse_listing(raw, listing_type)
                if listing:
                    results.append(listing)

    except (requests.RequestException, json.JSONDecodeError):
        pass

    return results


def _extract_next_data(html: str) -> Optional[dict]:
    import re
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _get_listings_from_json(data: dict) -> list:
    try:
        props = data.get("props", {}).get("pageProps", {})
        listings = props.get("listings", props.get("searchResult", {}).get("listings", []))
        return listings if isinstance(listings, list) else []
    except (KeyError, TypeError):
        return []


def _parse_listing(raw: dict, listing_type: str) -> Optional[Listing]:
    try:
        title = raw.get("title", raw.get("publicationTitle", ""))
        price = extract_int(str(raw.get("price", raw.get("rent", {}).get("amount", ""))))
        location = raw.get("city", raw.get("location", {}).get("city", ""))
        surface = extract_number(str(raw.get("surface", "")))
        rooms = extract_int(str(raw.get("rooms", raw.get("roomsNumber", ""))))
        url = raw.get("classifiedURL", raw.get("url", BASE_URL))
        if url and not url.startswith("http"):
            url = BASE_URL + url

        images = []
        photos = raw.get("photos", [])
        if isinstance(photos, list):
            images = [p.get("url", p) if isinstance(p, dict) else p for p in photos[:3]]

        prop_type = raw.get("propertyType", raw.get("type", "other")).lower()
        prop_map = {"appartement": "apartment", "maison": "house", "studio": "studio"}
        prop_type = prop_map.get(prop_type, prop_type)

        return Listing(
            site="SeLoger",
            title=title or "Annonce SeLoger",
            price=price,
            location=location,
            surface=surface,
            rooms=rooms,
            bedrooms=None,
            listing_type=listing_type,
            property_type=prop_type,
            url=url or BASE_URL,
            description=raw.get("description", "")[:300],
            images=images,
            agency=raw.get("agencyName", raw.get("agency", {}).get("name")),
        )
    except Exception:
        return None
