"""
PAP.fr scraper — particulier à particulier (no agencies).
Uses standard HTTP + BeautifulSoup; moderate anti-bot protection.
"""
import requests
from bs4 import BeautifulSoup
from typing import Optional
from .base import Listing, HEADERS, extract_int, extract_number
import re


BASE_URL = "https://www.pap.fr"


def _build_url(
    listing_type: str,
    location: str,
    property_type: str,
    max_price: Optional[int],
    min_surface: Optional[int],
    rooms: Optional[int],
) -> str:
    type_map = {
        "rent": "location",
        "sale": "vente",
    }
    prop_map = {
        "apartment": "appartement",
        "house": "maison",
        "studio": "studio",
        "any": "",
    }
    section = type_map.get(listing_type, "location")
    prop = prop_map.get(property_type, "")

    path = f"/{section}"
    if prop:
        path += f"/{prop}"

    params = []
    if location:
        params.append(f"g_ville={location.lower().replace(' ', '-')}")
    if max_price:
        params.append(f"prix_max={max_price}")
    if min_surface:
        params.append(f"surface_min={min_surface}")
    if rooms:
        params.append(f"nb_pieces_min={rooms}")

    url = BASE_URL + path
    if params:
        url += "?" + "&".join(params)
    return url


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
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = soup.select("div.search-list-item, article.search-list-item, .list-item-annonce")
        if not cards:
            cards = soup.select("[class*='liste-resultat'] > li, .resultat-list > li")

        for card in cards[:max_results]:
            try:
                listing = _parse_card(card, listing_type, url)
                if listing:
                    results.append(listing)
            except Exception:
                continue

    except requests.RequestException:
        pass

    return results


def _parse_card(card, listing_type: str, search_url: str) -> Optional[Listing]:
    title_el = card.select_one("a.item-title, h2 a, .title a, [class*='title'] a")
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    url = BASE_URL + href if href.startswith("/") else href

    price_el = card.select_one(".price, [class*='prix'], [class*='price']")
    price_text = price_el.get_text(strip=True) if price_el else ""
    price = extract_int(price_text)

    location_el = card.select_one(".item-description .ville, [class*='localite'], [class*='city']")
    location = location_el.get_text(strip=True) if location_el else ""

    surface_el = card.select_one("[class*='surface']")
    surface_text = surface_el.get_text(strip=True) if surface_el else ""
    surface = extract_number(surface_text)

    rooms_el = card.select_one("[class*='piece'], [class*='room']")
    rooms_text = rooms_el.get_text(strip=True) if rooms_el else ""
    rooms = extract_int(rooms_text)

    desc_el = card.select_one(".item-description p, [class*='description']")
    description = desc_el.get_text(strip=True) if desc_el else ""

    img_el = card.select_one("img")
    images = [img_el["src"]] if img_el and img_el.get("src") else []

    prop_type = _infer_property_type(title + " " + description)

    return Listing(
        site="PAP",
        title=title,
        price=price,
        location=location,
        surface=surface,
        rooms=rooms,
        bedrooms=None,
        listing_type=listing_type,
        property_type=prop_type,
        url=url,
        description=description,
        images=images,
    )


def _infer_property_type(text: str) -> str:
    text_lower = text.lower()
    if "studio" in text_lower:
        return "studio"
    if "maison" in text_lower or "villa" in text_lower:
        return "house"
    if "appartement" in text_lower or "appart" in text_lower:
        return "apartment"
    return "other"
