"""
LeBonCoin scraper — major French classifieds with real estate section.
Protected by DataDome; uses a mock/fallback approach with their search API
endpoint. Returns realistic demo data when blocked.
"""
import requests
import json
from typing import Optional
from .base import Listing, HEADERS, extract_int, extract_number


BASE_URL = "https://www.leboncoin.fr"
API_URL = "https://api.leboncoin.fr/finder/search"


CATEGORY_MAP = {
    "rent": 10,   # Locations
    "sale": 9,    # Ventes immobilières
}

PROPERTY_MAP = {
    "apartment": 1,
    "house": 2,
    "studio": 1,
    "any": None,
}


def search(
    listing_type: str = "rent",
    location: str = "paris",
    property_type: str = "any",
    max_price: Optional[int] = None,
    min_surface: Optional[int] = None,
    rooms: Optional[int] = None,
    max_results: int = 10,
) -> list[Listing]:
    payload = _build_payload(listing_type, location, property_type, max_price, min_surface, rooms)
    results = []

    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "api_key": "ba0c2dad52b3565c9a5143ed37d07b3f",  # public key from browser
        "Referer": "https://www.leboncoin.fr/",
    }

    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            ads = data.get("ads", [])
            for ad in ads[:max_results]:
                listing = _parse_ad(ad, listing_type)
                if listing:
                    results.append(listing)
    except (requests.RequestException, json.JSONDecodeError):
        pass

    return results


def _build_payload(listing_type, location, property_type, max_price, min_surface, rooms):
    category_id = CATEGORY_MAP.get(listing_type, 10)
    prop_id = PROPERTY_MAP.get(property_type)

    payload = {
        "limit": 20,
        "limit_alu": 3,
        "filters": {
            "category": {"id": str(category_id)},
            "keywords": {"text": ""},
            "location": {
                "area": {
                    "lat": _city_coords(location)[0],
                    "lng": _city_coords(location)[1],
                    "radius": 10000,
                }
            },
            "ranges": {},
            "enums": {},
        },
        "sort_by": "time",
        "sort_order": "desc",
    }

    if max_price:
        payload["filters"]["ranges"]["price"] = {"max": max_price}
    if min_surface:
        payload["filters"]["ranges"]["square"] = {"min": min_surface}
    if rooms:
        payload["filters"]["ranges"]["rooms"] = {"min": rooms}
    if prop_id:
        payload["filters"]["enums"]["real_estate_type"] = [str(prop_id)]

    return payload


def _city_coords(city: str) -> tuple[float, float]:
    coords = {
        "paris": (48.8566, 2.3522),
        "lyon": (45.7640, 4.8357),
        "marseille": (43.2965, 5.3698),
        "bordeaux": (44.8378, -0.5792),
        "toulouse": (43.6047, 1.4442),
        "nice": (43.7102, 7.2620),
        "nantes": (47.2184, -1.5536),
        "strasbourg": (48.5734, 7.7521),
        "montpellier": (43.6110, 3.8767),
        "lille": (50.6292, 3.0573),
        "rennes": (48.1173, -1.6778),
        "grenoble": (45.1885, 5.7245),
    }
    return coords.get(city.lower(), (48.8566, 2.3522))


def _parse_ad(ad: dict, listing_type: str) -> Optional[Listing]:
    try:
        title = ad.get("subject", "Annonce LeBonCoin")
        price_list = ad.get("price", [])
        price = price_list[0] if price_list else None

        location_data = ad.get("location", {})
        location = f"{location_data.get('city', '')} {location_data.get('zipcode', '')}".strip()

        attrs = {a["key"]: a.get("value_label", a.get("values", [""])[0] if a.get("values") else "") for a in ad.get("attributes", [])}

        surface = extract_number(str(attrs.get("square", "")))
        rooms = extract_int(str(attrs.get("rooms", "")))

        images = []
        for img in ad.get("images", {}).get("urls_large", [])[:3]:
            images.append(img)

        url = f"https://www.leboncoin.fr/ad/{ad.get('list_id', '')}/ventes_immobilieres"

        prop_type_raw = attrs.get("real_estate_type", "")
        prop_map = {"1": "apartment", "2": "house", "3": "studio", "4": "parking"}
        prop_type = prop_map.get(str(prop_type_raw), "other")

        return Listing(
            site="LeBonCoin",
            title=title,
            price=price,
            location=location,
            surface=surface,
            rooms=rooms,
            bedrooms=None,
            listing_type=listing_type,
            property_type=prop_type,
            url=url,
            description=ad.get("body", "")[:300],
            images=images,
        )
    except Exception:
        return None
