from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class Listing:
    site: str
    title: str
    price: Optional[int]
    location: str
    surface: Optional[float]
    rooms: Optional[int]
    bedrooms: Optional[int]
    listing_type: str  # "sale" or "rent"
    property_type: str  # "apartment", "house", "studio", etc.
    url: str
    description: str = ""
    images: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    agency: Optional[str] = None
    charges: Optional[int] = None  # monthly charges for rent

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "title": self.title,
            "price": self.price,
            "location": self.location,
            "surface": self.surface,
            "rooms": self.rooms,
            "bedrooms": self.bedrooms,
            "listing_type": self.listing_type,
            "property_type": self.property_type,
            "url": self.url,
            "description": self.description,
            "images": self.images,
            "features": self.features,
            "agency": self.agency,
            "charges": self.charges,
        }

    @staticmethod
    def price_per_m2(price: Optional[int], surface: Optional[float]) -> Optional[float]:
        if price and surface and surface > 0:
            return round(price / surface, 0)
        return None


def extract_number(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_int(text: str) -> Optional[int]:
    val = extract_number(text)
    return int(val) if val is not None else None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
