"""Explicit demo media and inventory. These are not live programs or product offers."""

PEOPLE = {"mom": "Mom", "leo": "Leo", "alex": "Alex"}

SCENES = {
    "park_chase": {
        "id": "park_chase",
        "title": "A little hare-raising afternoon",
        "subtitle": "One rabbit. One bulldog. Absolutely no brakes.",
        "category": "HomeBound original · 3D cartoon",
        "attention": "focused",
        "art": "park_chase",
        "items": [],
        "recipe": None,
        "stream": {
            "src": "/static/media/park-chase.mp4",
            "poster": "/static/media/park-chase-poster.jpg",
            "captions": "/static/media/park-chase.vtt",
            "duration": 60,
            "breaks": [
                {
                    "at": 20,
                    "src": "/static/media/movie-night-ad.mp4",
                    "duration": 6,
                    "title": "Make room for movie night",
                },
                {
                    "at": 42,
                    "src": "/static/media/popcorn-ad.mp4",
                    "duration": 6,
                    "title": "A little pause. A little popcorn.",
                },
            ],
        },
    },
    "coast": {
        "id": "coast",
        "title": "The quiet coast",
        "subtitle": "A journey north",
        "category": "Slow television",
        "attention": "casual",
        "art": "coast",
        "items": [],
        "recipe": None,
    },
    "cooking": {
        "id": "cooking",
        "title": "The weekend table",
        "subtitle": "Something good, from what you have",
        "category": "In the kitchen",
        "attention": "casual",
        "art": "cooking",
        "items": ["olive_oil"],
        "recipe": "lemon_pasta",
    },
    "movie": {
        "id": "movie",
        "title": "After the last light",
        "subtitle": "Some moments deserve your full attention",
        "category": "Movie night",
        "attention": "focused",
        "art": "movie",
        "items": ["field_jacket"],
        "recipe": None,
    },
    "game": {
        "id": "game",
        "title": "Matchday",
        "subtitle": "North FC  2 : 1  South United",
        "category": "Live sport preview",
        "attention": "focused",
        "art": "game",
        "items": [],
        "recipe": None,
    },
}

PRODUCTS = {
    "olive_oil": {
        "id": "olive_oil",
        "name": "Extra virgin olive oil",
        "detail": "500 ml · pantry essential",
        "price_minor": 950,
        "currency": "EUR",
        "art": "oil",
        "ingredient": "olive_oil",
    },
    "field_jacket": {
        "id": "field_jacket",
        "name": "The everyday field jacket",
        "detail": "Olive canvas · a similar style",
        "price_minor": 12900,
        "currency": "EUR",
        "art": "jacket",
        "ingredient": None,
    },
}

INGREDIENTS = {
    "pasta": "pasta",
    "lemon": "lemon",
    "parmesan": "parmesan",
    "olive_oil": "olive oil",
    "tomato": "tomatoes",
    "basil": "basil",
    "bread": "bread",
}

RECIPES = {
    "lemon_pasta": {
        "id": "lemon_pasta",
        "name": "Lemon & parmesan pasta",
        "minutes": 20,
        "description": "A little lemon, a handful of parmesan. Dinner, beautifully simple.",
        "ingredients": ["pasta", "lemon", "parmesan", "olive_oil"],
    },
    "tomato_toast": {
        "id": "tomato_toast",
        "name": "Garden tomato toast",
        "minutes": 10,
        "description": "Ripe tomatoes, fresh basil and warm, crisp bread.",
        "ingredients": ["tomato", "basil", "bread"],
    },
}

FIXTURE_NOTES = (
    {
        "id": "demo-leo",
        "recipient": "leo",
        "text": "Your math homework is due tomorrow.",
        "sender": "Mom",
    },
    {
        "id": "demo-mom",
        "recipient": "mom",
        "text": "I took the dog out. Enjoy your evening.",
        "sender": "Alex",
    },
)
