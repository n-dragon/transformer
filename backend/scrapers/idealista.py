"""
Idealista scraper — leading portal in Spain, Italy, Portugal.
Uses standard HTTP scraping with BeautifulSoup.
"""
import requests
from bs4 import BeautifulSoup
from typing import Optional
from .base import Listing, HEADERS, extract_int, extract_number
import re


BASE_URLS = {
    "spain": "https://www.idealista.com",
    "italy": "https://www.idealista.it",
    "portugal": "https://www.idealista.pt",
}

TRANSACTION_MAP = {
    "rent": "alquiler",
    "sale": "venta",
}


def search(
    listing_type: str = "rent",
    location: str = "madrid",
    property_type: str = "any",
    country: str = "spain",
    max_price: Optional[int] = None,
    min_surface: Optional[int] = None,
    rooms: Optional[int] = None,
    max_results: int = 10,
) -> list[Listing]:
    base = BASE_URLS.get(country, BASE_URLS["spain"])
    transaction = TRANSACTION_MAP.get(listing_type, "alquiler")
    prop = _property_path(property_type)

    url = f"{base}/{transaction}-{prop}/{_format_city(location)}/"
    params = []
    if max_price:
        params.append(f"precio-hasta_{max_price}")
    if min_surface:
        params.append(f"superficie-de_{min_surface}")
    if rooms:
        params.append(f"habitaciones-de_{rooms}")

    if params:
        url += ",".join(params) + "/"

    results = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = soup.select("article.item, .item-multimedia-container, [class*='listing-item']")
        for card in cards[:max_results]:
            listing = _parse_card(card, listing_type, base, country)
            if listing:
                results.append(listing)

    except requests.RequestException:
        pass

    return results


def _property_path(property_type: str) -> str:
    map_ = {
        "apartment": "pisos",
        "house": "casas",
        "studio": "pisos",
        "any": "inmuebles",
    }
    return map_.get(property_type, "inmuebles")


def _format_city(city: str) -> str:
    return city.lower().replace(" ", "-").replace("é", "e").replace("á", "a")


def _parse_card(card, listing_type: str, base_url: str, country: str) -> Optional[Listing]:
    try:
        link = card.select_one("a.item-link, [class*='item-link']")
        if not link:
            return None

        title = link.get("title", link.get_text(strip=True))
        href = link.get("href", "")
        url = base_url + href if href.startswith("/") else href

        price_el = card.select_one(".item-price, [class*='price']")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = extract_int(price_text)

        detail_items = card.select(".item-detail, [class*='detail']")
        surface = None
        rooms = None
        for detail in detail_items:
            text = detail.get_text(strip=True)
            if "m²" in text:
                surface = extract_number(text)
            elif re.search(r"\d\s*(hab|room|piece)", text, re.I):
                rooms = extract_int(text)

        location_el = card.select_one(".item-detail-char, [class*='location']")
        location = location_el.get_text(strip=True) if location_el else ""

        img_el = card.select_one("img")
        images = [img_el["src"]] if img_el and img_el.get("src") else []

        return Listing(
            site=f"Idealista ({country.capitalize()})",
            title=title,
            price=price,
            location=location,
            surface=surface,
            rooms=rooms,
            bedrooms=None,
            listing_type=listing_type,
            property_type="apartment",
            url=url,
            images=images,
        )
    except Exception:
        return None
