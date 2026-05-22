"""
Claude-powered real estate agent.
Uses tool_use to search listings across multiple sites.
"""
import anthropic
import json
import concurrent.futures
from typing import Optional, Generator
from scrapers import SCRAPERS, Listing


client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "search_listings",
        "description": (
            "Search real estate listings across major French and European portals. "
            "Returns matching properties for sale or rent based on the user's criteria. "
            "Use this tool to find housing options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_type": {
                    "type": "string",
                    "enum": ["rent", "sale"],
                    "description": "Whether to search for rentals or properties for sale",
                },
                "location": {
                    "type": "string",
                    "description": "City or area to search in (e.g. 'paris', 'lyon', 'bordeaux', 'madrid')",
                },
                "property_type": {
                    "type": "string",
                    "enum": ["apartment", "house", "studio", "any"],
                    "description": "Type of property to search for",
                },
                "max_price": {
                    "type": "integer",
                    "description": "Maximum price in euros (rent per month or sale price)",
                },
                "min_surface": {
                    "type": "integer",
                    "description": "Minimum surface area in square meters",
                },
                "rooms": {
                    "type": "integer",
                    "description": "Minimum number of rooms",
                },
                "sites": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["pap", "seloger", "leboncoin", "idealista"]},
                    "description": "Which sites to search. Defaults to pap and seloger for France.",
                },
            },
            "required": ["listing_type", "location"],
        },
    },
    {
        "name": "compare_listings",
        "description": "Compare multiple listings and highlight the best options based on price/m², features, and location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "string",
                    "description": "What to prioritize: 'price', 'surface', 'location', 'value'",
                },
            },
            "required": ["criteria"],
        },
    },
]

SYSTEM_PROMPT = """Tu es un agent immobilier expert qui aide les utilisateurs à trouver le logement idéal en France et en Europe.

Tu as accès à des outils pour rechercher des annonces sur les principaux portails immobiliers :
- **PAP** (particulier à particulier, sans agence)
- **SeLoger** (le plus grand portail français, avec agences)
- **LeBonCoin** (petites annonces incluant l'immobilier)
- **Idealista** (Espagne, Italie, Portugal)

Quand l'utilisateur décrit ce qu'il cherche, utilise l'outil search_listings pour trouver des annonces correspondantes.
Présente les résultats de façon claire avec les informations clés : prix, surface, localisation, lien.
Si tu trouves des annonces, compare-les et fais une recommandation personnalisée.
Réponds toujours en français sauf si l'utilisateur parle une autre langue."""


def _execute_search(
    listing_type: str,
    location: str,
    property_type: str = "any",
    max_price: Optional[int] = None,
    min_surface: Optional[int] = None,
    rooms: Optional[int] = None,
    sites: Optional[list] = None,
) -> list[dict]:
    if not sites:
        sites = ["pap", "seloger"]

    valid_sites = [s for s in sites if s in SCRAPERS]
    if not valid_sites:
        valid_sites = ["pap", "seloger"]

    all_results: list[Listing] = []

    def fetch(site_name: str):
        scraper = SCRAPERS[site_name]
        kwargs = dict(
            listing_type=listing_type,
            location=location,
            property_type=property_type,
            max_price=max_price,
            min_surface=min_surface,
            rooms=rooms,
            max_results=5,
        )
        if site_name == "idealista":
            country = _infer_country(location)
            kwargs["country"] = country
            del kwargs["listing_type"]
            kwargs["listing_type"] = listing_type
        try:
            return scraper.search(**kwargs)
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch, site): site for site in valid_sites}
        for future in concurrent.futures.as_completed(futures):
            all_results.extend(future.result())

    return [l.to_dict() for l in all_results]


def _infer_country(location: str) -> str:
    spain_cities = {"madrid", "barcelona", "valencia", "seville", "bilbao", "malaga"}
    italy_cities = {"rome", "milan", "florence", "venice", "naples", "turin"}
    portugal_cities = {"lisbon", "porto", "faro"}
    loc = location.lower()
    if loc in spain_cities:
        return "spain"
    if loc in italy_cities:
        return "italy"
    if loc in portugal_cities:
        return "portugal"
    return "spain"


def _format_search_results(results: list[dict]) -> str:
    if not results:
        return "Aucune annonce trouvée pour ces critères. Essaie d'élargir ta recherche (ville différente, budget plus élevé, ou moins de filtres)."

    lines = [f"**{len(results)} annonce(s) trouvée(s) :**\n"]
    for i, r in enumerate(results, 1):
        price_str = f"{r['price']:,} €".replace(",", " ") if r["price"] else "Prix non communiqué"
        surface_str = f"{r['surface']} m²" if r["surface"] else "Surface inconnue"
        rooms_str = f"{r['rooms']} pièce(s)" if r["rooms"] else ""
        loc = r["location"] or "Localisation inconnue"

        lines.append(
            f"**{i}. [{r['title']}]({r['url']})**  \n"
            f"   📍 {loc} — 💰 {price_str} — 📐 {surface_str}"
            + (f" — 🚪 {rooms_str}" if rooms_str else "")
            + f"  \n   🏠 {r['site']} | {r['property_type']}"
            + (f"\n   _{r['description'][:120]}..._" if r["description"] else "")
            + "\n"
        )

    return "\n".join(lines)


def run_agent(user_message: str, conversation_history: list[dict]) -> Generator[str, None, None]:
    messages = conversation_history + [{"role": "user", "content": user_message}]

    found_listings: list[dict] = []

    while True:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    yield block.text
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            text_so_far = []

            for block in response.content:
                if hasattr(block, "text"):
                    text_so_far.append(block.text)
                elif block.type == "tool_use":
                    if block.name == "search_listings":
                        yield f"\n🔍 Recherche en cours sur {', '.join(block.input.get('sites', ['pap', 'seloger']))}...\n"

                        results = _execute_search(**block.input)
                        found_listings.extend(results)
                        result_text = _format_search_results(results)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                    elif block.name == "compare_listings":
                        comparison = _compare(found_listings, block.input.get("criteria", "value"))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": comparison,
                        })

            if text_so_far:
                yield "\n".join(text_so_far)

            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]
        else:
            break


def _compare(listings: list[dict], criteria: str) -> str:
    if not listings:
        return "Pas encore d'annonces à comparer."

    if criteria == "price":
        sorted_l = sorted(listings, key=lambda x: x.get("price") or 9_999_999)
    elif criteria == "surface":
        sorted_l = sorted(listings, key=lambda x: x.get("surface") or 0, reverse=True)
    elif criteria == "value":
        def value_score(l):
            if l.get("price") and l.get("surface") and l["surface"] > 0:
                return l["price"] / l["surface"]
            return 9_999_999
        sorted_l = sorted(listings, key=value_score)
    else:
        sorted_l = listings

    lines = ["Comparaison des annonces :\n"]
    for i, l in enumerate(sorted_l[:5], 1):
        ppm2 = None
        if l.get("price") and l.get("surface") and l["surface"] > 0:
            ppm2 = round(l["price"] / l["surface"])
        lines.append(
            f"{i}. {l['title']} ({l['site']}) — {l.get('price', '?')} € — "
            f"{l.get('surface', '?')} m²"
            + (f" — {ppm2} €/m²" if ppm2 else "")
        )

    return "\n".join(lines)
