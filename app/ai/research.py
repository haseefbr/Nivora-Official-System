"""Offline recipe knowledge, used when no model answers.

This is not the AI. It is a small curated table of ordinary Malaysian recipes so
the buyer→order→recipe flow still works on a laptop with no model. The call log
records provider="local-rules" and model="local-recipe-kb", and every idea is
still checked (no prices, at least three ingredients) before a person sees it.
"""
from __future__ import annotations

from .text import normalize

RECIPE_KB: dict[str, dict] = {
    "nasi lemak": {
        "yield_units": 10,
        "ingredients": [
            ("beras", 1000, "g"), ("santan", 400, "ml"), ("telur", 10, "biji"),
            ("ikan bilis", 150, "g"), ("kacang tanah", 150, "g"), ("sambal", 300, "g"),
            ("timun", 2, "batang"),
        ],
        "steps": ["Masak nasi dengan santan dan pandan.", "Goreng ikan bilis dan kacang.",
                  "Rebus telur.", "Hidang dengan sambal dan timun."],
    },
    "nasi ayam": {
        "yield_units": 8,
        "ingredients": [
            ("beras", 800, "g"), ("ayam", 1200, "g"), ("halia", 80, "g"),
            ("bawang putih", 60, "g"), ("kicap", 120, "ml"), ("sos cili", 200, "ml"),
        ],
        "steps": ["Rebus ayam dengan halia.", "Masak nasi dengan air rebusan ayam.",
                  "Perap ayam dengan kicap.", "Hidang dengan sos cili."],
    },
    "kuih lapis": {
        "yield_units": 40,
        "ingredients": [
            ("tepung beras", 400, "g"), ("gula", 300, "g"), ("santan", 200, "ml"),
            ("pewarna", 20, "ml"),
        ],
        "steps": ["Campur semua bahan.", "Kukus selapis demi selapis.", "Sejukkan sebelum potong."],
    },
    "karipap": {
        "yield_units": 30,
        "ingredients": [
            ("tepung gandum", 500, "g"), ("marjerin", 150, "g"), ("kentang", 600, "g"),
            ("bawang merah", 100, "g"), ("kari serbuk", 30, "g"),
        ],
        "steps": ["Uli doh dengan marjerin.", "Masak inti kentang dengan kari.",
                  "Bungkus dan goreng hingga keemasan."],
    },
    "pineapple tart": {
        "yield_units": 60,
        "ingredients": [
            ("tepung gandum", 1000, "g"), ("mentega", 500, "g"), ("jem nanas", 800, "g"),
            ("telur", 3, "biji"),
        ],
        "steps": ["Uli doh mentega.", "Balut jem nanas.", "Sapu telur dan bakar."],
    },
    "spaghetti carbonara": {
        "yield_units": 4,
        "ingredients": [
            ("spaghetti", 400, "g"), ("krim", 250, "ml"), ("ayam salai", 300, "g"),
            ("parmesan", 80, "g"), ("bawang putih", 30, "g"),
        ],
        "steps": ["Rebus spaghetti.", "Tumis bawang dan ayam.", "Campur krim dan keju."],
    },
    "creamy tomyam noodles": {
        "yield_units": 4,
        "ingredients": [
            ("mee", 400, "g"), ("pes tomyam", 100, "g"), ("santan", 200, "ml"),
            ("udang", 300, "g"), ("cendawan", 150, "g"),
        ],
        "steps": ["Didihkan pes tomyam dengan air.", "Masuk santan dan udang.",
                  "Masak mee dan hidang."],
    },
    "crispy chicken burger": {
        "yield_units": 4,
        "ingredients": [
            ("roti burger", 4, "biji"), ("ayam", 600, "g"), ("tepung gandum", 200, "g"),
            ("mayonis", 100, "g"), ("keju", 4, "keping"),
        ],
        "steps": ["Perap dan salut ayam.", "Goreng hingga rangup.", "Susun dalam roti."],
    },
    "french fries": {
        "yield_units": 4,
        "ingredients": [("kentang", 800, "g"), ("garam", 10, "g"), ("minyak", 500, "ml")],
        "steps": ["Potong kentang.", "Goreng dua kali.", "Tabur garam."],
    },
    "chocolate brownies": {
        "yield_units": 16,
        "ingredients": [
            ("coklat masakan", 300, "g"), ("mentega", 200, "g"), ("gula", 250, "g"),
            ("telur", 4, "biji"), ("tepung gandum", 150, "g"),
        ],
        "steps": ["Cairkan coklat dan mentega.", "Campur telur dan gula.", "Bakar 25 minit."],
    },
    "strawberry cheesecake": {
        "yield_units": 10,
        "ingredients": [
            ("cream cheese", 500, "g"), ("biskut", 200, "g"), ("mentega", 100, "g"),
            ("gula", 150, "g"), ("strawberi", 300, "g"),
        ],
        "steps": ["Hancurkan biskut dengan mentega.", "Pukul cream cheese dan gula.",
                  "Bakar dan hiaskan strawberi."],
    },
    "matcha latte": {
        "yield_units": 2,
        "ingredients": [("matcha", 10, "g"), ("susu", 400, "ml"), ("gula", 20, "g")],
        "steps": ["Pukul matcha dengan air panas.", "Campur susu.", "Tambah ais."],
    },
    "iced lemon tea": {
        "yield_units": 2,
        "ingredients": [("teh", 10, "g"), ("lemon", 2, "biji"), ("gula", 30, "g"), ("ais", 200, "g")],
        "steps": ["Seduh teh.", "Tambah lemon dan gula.", "Sejukkan dengan ais."],
    },
    "buttermilk chicken rice": {
        "yield_units": 4,
        "ingredients": [
            ("ayam", 800, "g"), ("susu", 200, "ml"), ("tepung gandum", 150, "g"),
            ("mentega", 80, "g"), ("daun kari", 10, "g"), ("beras", 600, "g"),
        ],
        "steps": ["Perap ayam dengan susu.", "Goreng ayam.", "Masak sos mentega dan daun kari."],
    },
}


def heuristic_research(dish: str) -> dict:
    key = normalize(dish)
    entry = None
    for name, recipe in RECIPE_KB.items():
        if name in key or key in name:
            entry = recipe
            break
    if entry is None:
        return {
            "dish": dish[:120] or "Unknown dish",
            "yield_units": 1,
            "ingredients": [],
            "steps": [],
            "confidence": 0.1,
        }
    return {
        "dish": dish[:120],
        "yield_units": entry["yield_units"],
        "ingredients": [
            {"ingredient": name, "quantity": quantity, "unit": unit}
            for name, quantity, unit in entry["ingredients"]
        ],
        "steps": entry["steps"],
        "confidence": 0.62,
    }
