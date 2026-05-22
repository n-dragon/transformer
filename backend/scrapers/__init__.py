from .base import Listing
from . import pap, seloger, leboncoin, idealista

SCRAPERS = {
    "pap": pap,
    "seloger": seloger,
    "leboncoin": leboncoin,
    "idealista": idealista,
}

__all__ = ["Listing", "SCRAPERS"]
