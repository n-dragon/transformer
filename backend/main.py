"""
FastAPI backend for the real estate agent web app.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from agent import run_agent

app = FastAPI(title="ImmoAgent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class AgentConfig(BaseModel):
    name: str
    listing_type: str = "rent"
    location: str = "paris"
    property_type: str = "any"
    max_price: int | None = None
    min_surface: int | None = None
    rooms: int | None = None
    sites: list[str] = ["pap", "seloger"]


@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ImmoAgent API is running. Frontend not found."}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    def generate():
        try:
            for chunk in run_agent(req.message, req.history):
                data = json.dumps({"type": "text", "content": chunk})
                yield f"data: {data}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/sites")
async def list_sites():
    return {
        "sites": [
            {
                "id": "pap",
                "name": "PAP.fr",
                "description": "Particulier à particulier — annonces sans agence",
                "country": "France",
                "url": "https://www.pap.fr",
                "supports": ["rent", "sale"],
                "scraping": "HTTP + BeautifulSoup",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "seloger",
                "name": "SeLoger.com",
                "description": "Le plus grand portail immobilier français",
                "country": "France",
                "url": "https://www.seloger.com",
                "supports": ["rent", "sale"],
                "scraping": "__NEXT_DATA__ JSON extraction",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "leboncoin",
                "name": "LeBonCoin",
                "description": "Petites annonces — section immobilier",
                "country": "France",
                "url": "https://www.leboncoin.fr",
                "supports": ["rent", "sale"],
                "scraping": "API interne reverse-engineered",
                "anti_bot": "Fort (DataDome)",
                "api": False,
            },
            {
                "id": "logic_immo",
                "name": "Logic-Immo",
                "description": "Portail avec agences et promoteurs",
                "country": "France",
                "url": "https://www.logic-immo.com",
                "supports": ["rent", "sale"],
                "scraping": "HTTP scraping",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "bienici",
                "name": "Bien'ici",
                "description": "Portail des agences immobilières françaises",
                "country": "France",
                "url": "https://www.bienici.com",
                "supports": ["rent", "sale"],
                "scraping": "HTTP + JSON API",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "idealista",
                "name": "Idealista",
                "description": "Leader en Espagne, Italie et Portugal",
                "country": "Espagne / Italie / Portugal",
                "url": "https://www.idealista.com",
                "supports": ["rent", "sale"],
                "scraping": "HTTP + BeautifulSoup",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "immobilienscout24",
                "name": "ImmoScout24",
                "description": "Leader de l'immobilier en Allemagne",
                "country": "Allemagne",
                "url": "https://www.immobilienscout24.de",
                "supports": ["rent", "sale"],
                "scraping": "API cachée reverse-engineered",
                "anti_bot": "Fort",
                "api": "Partenaires uniquement",
            },
            {
                "id": "rightmove",
                "name": "Rightmove",
                "description": "Le plus grand portail immobilier du Royaume-Uni",
                "country": "Royaume-Uni",
                "url": "https://www.rightmove.co.uk",
                "supports": ["rent", "sale"],
                "scraping": "__NEXT_DATA__ JSON extraction",
                "anti_bot": "Modéré",
                "api": "Partenaires uniquement",
            },
            {
                "id": "zoopla",
                "name": "Zoopla",
                "description": "Deuxième portail UK avec valorisations",
                "country": "Royaume-Uni",
                "url": "https://www.zoopla.co.uk",
                "supports": ["rent", "sale"],
                "scraping": "HTTP + automation navigateur",
                "anti_bot": "Modéré",
                "api": False,
            },
            {
                "id": "immowelt",
                "name": "Immowelt",
                "description": "Second portail immobilier allemand",
                "country": "Allemagne",
                "url": "https://www.immowelt.de",
                "supports": ["rent", "sale"],
                "scraping": "HTTP direct — peu protégé",
                "anti_bot": "Faible",
                "api": False,
            },
        ]
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
