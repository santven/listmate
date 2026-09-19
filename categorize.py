#!/usr/bin/env python3
"""Auto-categorize grocery items by keyword matching, peer learning, and Gemini AI.
Comprehensive mapping covering Western + Indian grocery items.
Loaded once at startup, queried at insert time, and used for daily cron sweeps."""

import re
import os
import sys
import json
import urllib.request

CANONICAL_CATEGORIES = [
    "Produce", "Dairy", "Bakery", "Meat & Seafood", "Deli",
    "Spices & Seasonings", "Legumes & Grains", "Canned & Jarred",
    "Dips & Spreads", "Nuts & Seeds", "Snacks & Sweets", "Beverages",
    "Frozen", "Household", "Health & Personal Care", "Indian Specialties"
]

CATEGORY_KEYWORDS = {
    # ── Meat & Seafood ──
    "Meat & Seafood": [
        "chicken", "poultry", "turkey", "duck", "beef", "steak", "ground beef",
        "pork", "pork chop", "bacon", "sausage", "ham", "lamb", "mutton", "goat",
        "salmon", "tuna", "fish", "tilapia", "cod", "halibut", "trout", "mahi mahi",
        "shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop",
        "squid", "calamari", "anchovy", "sardine", "meatball", "hot dog", "frankfurter",
        "impossible burger", "beyond burger", "impossible meat", "beyond meat",
        "chicken breast", "chicken thigh", "chicken wing", "chicken tender",
        "ribeye", "sirloin", "filet mignon", "short rib", "pork tenderloin",
        "pork loin", "baby back ribs", "ground chicken", "ground turkey", "ground pork",
        "beef patty", "beef patties", "burger patty", "burger patties",
    ],
    # ── Deli ──
    "Deli": [
        "deli", "deli turkey", "deli ham", "roast beef", "salami", "prosciutto",
        "pepperoni", "bologna", "pastrami", "rotisserie chicken", "cold cut",
        "prepared meal", "potato salad", "cole slaw", "macaroni salad",
        "lunch meat", "mortadella", "capocollo",
    ],
    # ── Health & Personal Care ──
    "Health & Personal Care": [
        "psyllium", "psyllium husk", "optifiber", "fiber supplement", "dietary fiber",
        "greens powder", "super greens powder", "supergreens powder", "supergreen powder",
        "vitamin", "multivitamin", "supplement", "creatine", "protein powder", "whey",
        "bcaa", "pre workout", "collagen", "biotin", "calcium", "magnesium", "probiotic",
        "omega 3", "fish oil", "zinc", "iron supplement", "one a day", "centrum",
        "nature made", "airborne", "emergen-c", "advil", "tylenol", "aspirin", "ibuprofen",
        "band aid", "bandaid", "bandage", "first aid", "medicine", "pill", "cough drop",
        "cough syrup", "antacid", "tums", "pepto", "pepto bismol", "electrolyte powder",
        "claritin", "zyrtec", "allegra", "benadryl", "flonase", "nasal spray",
        "saline spray", "sudafed", "mucinex", "robitussin", "dayquil", "nyquil",
        "motrin", "aleve", "naproxen", "allergy relief", "pain relief",
        "antihistamine", "decongestant", "lip balm", "chapstick", "burt's bees",
        "thermometer", "eye drops", "visine", "contact lens solution",
    ],
    # ── Produce: Top-level for produce section ──
    "Produce": [
        # Tofu / Plant proteins
        "silken tofu", "firm tofu", "extra firm tofu", "tofu", "tempeh", "seitan",
        # Vegetables
        "onion", "tomato", "potato", "ginger", "garlic", "carrot", "cucumber",
        "spinach", "kale", "lettuce", "arugula", "chard", "collard", "bok choy",
        "broccoli", "cauliflower", "cabbage", "brussels sprout", "asparagus",
        "celery", "bell pepper", "green pepper", "red pepper", "yellow pepper",
        "sweet pepper", "chili pepper", "pepper", "capsicum", "jalapeno", "serrano", "habanero",
        "poblano", "anaheim", "chili", "chilli", "green bean", "okra", "bhindi", "lady finger",
        "eggplant", "brinjal", "aubergine", "zucchini", "squash", "pumpkin",
        "sweet potato", "yam", "radish", "mooli", "daikon", "turnip",
        "beet", "beetroot", "corn", "maize", "peas", "mushroom",
        "fenugreek", "methi", "amaranth", "drumstick", "moringa",
        "bottle gourd", "lauki", "dudhi", "bitter gourd", "karela",
        "ridge gourd", "turai", "ivy gourd", "tindora", "kundru",
        "cluster bean", "guar", "pointed gourd", "parwal",
        "snake gourd", "padwal", "chayote", "chow chow", "leek",
        "fennel bulb", "artichoke", "taro", "arbi", "colocasia",
        "water chestnut", "singhara", "lotus stem", "kamal kakdi",
        "jackfruit", "raw banana", "plantain", "vazhakkai",
        "scallion", "green onion", "spring onion", "shallot",
        "sprout", "bean sprout", "alfalfa", "microgreen", "supergreen", "supergreens", "spring mix",
        "romaine", "romaine heart", "romaine hearts", "iceberg", "mixed greens", "salad mix",
        "cremini", "portobello", "shiitake", "oyster mushroom", "spaghetti squash",
        "butternut squash", "acorn squash", "yellow squash",
        # Fresh herbs
        "cilantro", "coriander leaf", "coriander leaves", "mint", "pudina", "basil", "tulsi",
        "curry leaf", "curry leaves", "kariveppilai", "dill", "parsley", "rosemary",
        "thyme", "sage", "oregano", "chive", "lemongrass", "tarragon",
        # Fruit
        "apple", "banana", "orange", "grape", "mango", "pineapple",
        "watermelon", "cantaloupe", "honeydew", "melon", "papaya", "guava",
        "pomegranate", "anar", "kiwi", "peach", "plum", "nectarine",
        "apricot", "pear", "cherry", "strawberry", "blueberry", "raspberry",
        "blackberry", "cranberry", "berry", "gooseberry", "mulberry",
        "fig", "date", "lychee", "rambutan",
        "dragon fruit", "star fruit", "custard apple", "sitaphal",
        "sapota", "chikoo", "tender coconut",
        "lemon", "lime", "nimbu", "avocado", "coconut",
        "clementine", "mandarin", "tangerine", "grapefruit",
    ],

    # ── Dairy ──
    "Dairy": [
        "milk", "butter", "ghee", "yogurt", "curd", "dahi", "yoghurt",
        "buttermilk", "chaas", "moru", "ice cream", "whipped cream", "heavy cream", "sour cream", "half and half",
        "cream cheese", "creamcheese",
        "cheese", "cheddar", "mozzarella", "parmesan", "swiss", "feta",
        "ricotta", "mascarpone", "brie", "gouda", "paneer",
        "cottage cheese", "cottagecheese", "queso", "monterey jack",
        "colby", "american cheese", "cheese slice", "string cheese",
        "egg", "egg white", "eggwhite", "egg yolk", "kefir",
        "protein yogurt", "protein yoghurt", "greek yogurt",
        "skyr", "labneh", "khoya", "mawa", "condensed milk",
        "evaporated milk", "lactose free milk", "a2 milk", "fairlife",
        "oat milk", "almond milk", "soy milk", "coconut milk",
        "coffee creamer", "probiotic", "yogurt drink", "lassi",
    ],

    # ── Bakery ──
    "Bakery": [
        "bread", "bun", "roll", "bagel", "croissant", "muffin",
        "tortilla", "wrap", "pita", "naan", "roti", "paratha",
        "pav", "pau", "brioche", "ciabatta", "focaccia", "baguette",
        "sourdough", "rye", "multigrain", "whole wheat bread",
        "white bread", "brown bread", "english muffin", "crumpet",
        "danish", "donut", "doughnut", "pastry", "cake", "cupcake",
        "pie crust", "pie shell", "pizza dough", "pizza base",
        "breadcrumb", "bread crumb", "crouton", "stuffing",
        "sandwich bread", "sandwich loaf", "rusk", "biscotti",
        "oatnut", "brownberry", "dave's killer", "nature's own", "arnold", "wonder bread",
        "garlic bread", "banana bread", "apple pie", "pumpkin pie", "pecan pie",
    ],

    # ── Legumes & Grains ──
    "Legumes & Grains": [
        "cereal", "cereals", "cheerios", "kellogg", "kelloggs", "corn flakes",
        "granola", "muesli", "rice krispies", "special k",
        "chickpea", "chana", "chole", "channa", "garbanzo",
        "dal", "dhal", "lentil", "toor", "tuvar", "arhar",
        "moong", "mung", "masoor", "urad", "urid", "udad",
        "rajma", "kidney bean", "black bean", "pinto bean",
        "navy bean", "cannellini", "lima bean", "fava bean",
        "soybean", "edamame", "black eyed pea", "lobia", "chawli",
        "rice", "basmati", "jasmine", "sona masoori", "ponni",
        "brown rice", "arborio", "parboiled", "idli rice",
        "quinoa", "millet", "ragi", "finger millet", "bajra",
        "jowar", "sorghum", "barley", "oats", "oatmeal", "oat",
        "steel cut oat", "steelcut oat", "rolled oat",
        "wheat", "atta", "flour", "maida", "all purpose flour",
        "whole wheat flour", "semolina", "sooji", "rava", "suji",
        "couscous", "bulgur", "farro", "amaranth", "teff",
        "pasta", "spaghetti", "penne", "macaroni", "fettuccine",
        "linguine", "ravioli", "tortellini", "lasagna", "noodle",
        "vermicelli", "sevai", "rice noodle", "somen", "udon", "ramen",
        "sabudana", "sago", "tapioca", "arrowroot",
        "poha", "flattened rice", "chivda", "murmura", "puffed rice",
        "corn meal", "polenta", "grits", "cornflour", "cornstarch",
        "mac and cheese", "macaroni and cheese",
    ],

    # ── Spices & Seasonings ──
    "Spices & Seasonings": [
        "coriander seed", "coriander seeds", "cumin seed", "mustard seed",
        "fenugreek seed", "fennel seed", "carom seed", "nigella seed", "sesame seed",
        "poppy seed", "turmeric", "haldi", "cumin", "jeera", "coriander powder",
        "dhania", "chili powder", "red chili", "kashmiri chili",
        "garam masala", "sambar powder", "rasam powder", "curry powder",
        "rai", "sarson", "methi seed",
        "asafoetida", "hing", "cardamom", "elaichi", "cinnamon", "dalchini",
        "clove", "laung", "black pepper", "kali mirch", "peppercorn",
        "nutmeg", "jaiphal", "mace", "javitri", "star anise",
        "bay leaf", "tej patta", "saunf", "ajwain", "kalonji",
        "khus khus", "til", "tamarind", "imli", "kokum", "amchur", "dry mango powder",
        "chaat masala", "pav bhaji masala", "chole masala",
        "biryani masala", "tandoori masala", "kitchen king",
        "salt", "pink salt", "black salt", "kala namak", "sea salt", "kosher salt",
        "vanilla extract", "vanilla essence", "baking powder",
        "baking soda", "yeast", "gelatin", "agar agar",
        "cocoa powder", "chocolate chip", "sprinkle",
        "italian seasoning", "paprika", "cayenne",
        "five spice", "szechuan", "soy sauce", "vinegar",
        "balsamic", "apple cider vinegar", "rice vinegar",
        "worcestershire", "fish sauce", "oyster sauce",
        "olive oil", "vegetable oil", "canola oil", "sunflower oil",
        "coconut oil", "sesame oil", "mustard oil", "peanut oil",
        "cooking spray", "pam", "avocado oil", "grapeseed oil", "oil", "cooking oil",
        "seasoning blend", "spice blend", "everything bagel seasoning", "garlic powder", "onion powder",
    ],

    # ── Snacks & Sweets ──
    "Snacks & Sweets": [
        "chip", "crisp", "cheeto", "dorito", "tortilla chip", "nacho",
        "pretzel", "popcorn", "cracker", "rice cake", "granola bar",
        "protein bar", "energy bar", "candy", "chocolate", "gummy",
        "cookie", "biscuit", "wafer", "namkeen", "bhujia", "sev",
        "mixture", "chakli", "murukku", "khakhra",
        "samosa", "pakora", "vada", "khaman", "dhokla",
        "halwa", "laddu", "ladoo", "barfi", "burfi", "jalebi",
        "gulab jamun", "rasgulla", "peda", "kaju katli", "mysore pak",
        "soan papdi", "petha", "sandesh", "kheer mix",
        "gelato", "sorbet", "frozen yogurt", "popsicle", "kulfi",
        "falooda", "cake mix", "brownie mix", "pancake mix",
        "jam", "jelly", "marmalade", "preserve", "honey",
        "maple syrup", "agave", "chocolate syrup", "caramel",
        "peanut butter", "almond butter", "cashew butter", "nutella",
        "oreo", "oreos", "double stuf", "cheez it", "cheez-it", "goldfish", "ritz",
    ],

    # ── Beverages ──
    "Beverages": [
        "coffee", "tea", "chai", "espresso", "latte", "cappuccino",
        "green tea", "black tea", "herbal tea", "matcha", "chai patti",
        "water", "sparkling water", "soda", "seltzer", "club soda",
        "tonic", "juice", "orange juice", "apple juice", "cranberry juice",
        "lemonade", "smoothie", "milkshake", "protein shake",
        "coconut water",
        "soft drink", "coke", "pepsi", "sprite", "ginger ale",
        "kombucha", "beer", "wine", "liquor", "spirit",
        "electrolyte", "gatorade", "powerade", "pedia",
        "energy drink", "red bull", "monster energy", "celsius",
    ],

    # ── Frozen ──
    "Frozen": [
        "frozen", "freezer", "frozen vegetable", "frozen fruit",
        "frozen pizza", "frozen dinner", "frozen meal", "frozen paratha",
        "frozen naan", "frozen roti", "frozen paneer", "frozen samosa",
        "frozen peas", "frozen corn", "frozen spinach", "frozen okra",
        "frozen bhindi", "frozen mixed vegetable",
        "frozen berry", "frozen mango", "frozen coconut",
        "ice cube", "frozen waffle", "frozen french fry", "tater tot",
    ],

    # ── Household ──
    "Household": [
        "lizol", "oxiclean", "stain remover", "reusable cup", "paper cup", "plastic cup",
        "paper plate", "plastic cutlery", "napkin", "paper towel", "tissue",
        "toilet paper", "kleenex", "trash bag", "garbage bag", "ziploc",
        "foil", "aluminum foil", "plastic wrap", "cling wrap", "parchment paper",
        "wax paper", "sponge", "scrub", "scrubber", "broom", "mop", "duster",
        "glove", "rubber gloves", "battery", "light bulb", "air freshener", "candle",
        "dish soap", "dishwasher", "dishwasher pod", "detergent", "laundry",
        "fabric softener", "bleach", "cleaner", "cleaning spray", "wipe",
        "disinfectant", "lysol", "clorox", "windex", "tide", "dawn",
        "toothpaste", "toothbrush", "dental floss", "floss", "mouthwash", "mouth wash",
        "shampoo", "conditioner", "body wash", "soap", "hand soap", "bar soap",
        "hand sanitizer", "sanitizer", "lotion", "body lotion", "sunscreen",
        "deodorant", "razor", "shaving", "shaving cream", "shaving foam", "shaving gel",
        "tampon", "pad", "diaper", "baby wipes", "cotton ball", "cotton swab", "q tip",
        "charmin", "bounty", "cottonelle", "angel soft", "bath tissue", "facial tissue",
        "scott", "glad", "hefty", "cascade", "palmolive", "ajax", "febreze", "swiffer", "finish",
    ],

    # ── Dips & Spreads ──
    "Dips & Spreads": [
        "hummus", "baba ghanoush", "tzatziki", "guacamole", "salsa",
        "pico de gallo", "queso dip", "ranch", "blue cheese dressing",
        "vinaigrette", "dressing", "mayonnaise", "mayo", "ketchup",
        "mustard", "bbq sauce", "barbecue sauce", "hot sauce", "sriracha",
        "chutney", "raita", "achaar", "pickle", "achar", "thokku",
        "pesto", "tapenade", "tahini", "chimichurri", "marmite",
        "vegemite", "nut butter", "seed butter", "mango pickle",
        "lemon pickle", "lime pickle", "garlic chutney", "coconut chutney",
        "coriander chutney", "mint chutney", "tamarind chutney",
        "tomato chutney", "onion chutney", "peanut chutney",
        "gongura", "pulihora mix", "spread", "dip",
    ],

    # ── Canned & Jarred ──
    "Canned & Jarred": [
        "canned", "canned tomato", "canned bean",
        "canned corn", "canned tuna", "canned soup", "canned fruit",
        "coconut cream", "jarred",
        "pasta sauce", "marinara", "tomato sauce", "tomato paste",
        "artichoke heart", "olive", "caper", "sundried tomato",
        "roasted red pepper", "pickled", "gherkin",
        "sauerkraut", "kimchi", "bamboo shoot",
        "baby corn", "curry paste", "thai paste", "red curry",
        "green curry", "miso", "doenjang", "gochujang",
        "broth", "chicken broth", "beef broth", "vegetable broth", "bone broth",
        "bouillon", "soup", "tomato soup", "chicken noodle soup", "clam chowder",
    ],

    # ── Nuts & Seeds ──
    "Nuts & Seeds": [
        "almond", "cashew", "walnut", "pecan", "pistachio", "macadamia",
        "brazil nut", "hazelnut", "pine nut", "peanut", "jumbo peanut", "mungfali",
        "sunflower seed", "pumpkin seed", "chia seed", "flax seed",
        "hemp seed", "hemp heart", "watermelon seed", "muskmelon seed",
        "trail mix", "mixed nut", "roasted chana", "bhuna chana",
        "fox nut", "makhana", "lotus seed", "phool makhana",
    ],

    # ── Indian Specialties ──
    "Indian Specialties": [
        "idli", "dosa", "medu vada", "vada", "uttapam", "appam",
        "idiyappam", "puttu", "ada", "modak", "kozhukattai",
        "pongal", "ven pongal", "sakkarai pongal", "upma", "uppittu",
        "bisi bele bath", "puliyogare", "lemon rice", "tamarind rice",
        "coconut rice", "curd rice", "thayir sadam", "bisibelebath",
        "sambar", "rasam", "kadhi", "moru curry", "avial",
        "poriyal", "thoran", "kootu", "pachadi",
        "papad", "appalam", "vadam", "vathal", "fryum",
        "moringa powder", "drumstick leaf powder", "sathu maavu",
        "health mix", "kanji", "porridge", "ragi malt",
        "pani puri", "golgappa", "sev puri", "bhel puri", "dahi puri",
        "pani puri kit", "chaat kit", "chaat",
        "jaggery", "gud", "vellam",
        "nariyal", "thengai", "desiccated coconut",
        "kobbari", "copra", "grated coconut", "coconut milk powder",
        "kolam", "sugar candy", "kalkandu", "palm sugar",
        "vathakuzhambu", "kara kuzhambu", "puli kuzhambu",
        "molagai podi", "gunpowder", "idli podi", "milagai podi",
        "idli rava",
    ],
}

# ── Irregular plurals and stemming table ──
IRREGULAR_PLURALS = {
    'leaves': 'leaf', 'halves': 'half', 'loaves': 'loaf', 'knives': 'knife',
    'tomatoes': 'tomato', 'potatoes': 'potato', 'mangoes': 'mango',
    'berries': 'berry', 'cherries': 'cherry', 'strawberries': 'strawberry',
    'blueberries': 'blueberry', 'raspberries': 'raspberry', 'blackberries': 'blackberry',
    'cranberries': 'cranberry', 'radishes': 'radish', 'sausages': 'sausage',
    'cheeses': 'cheese', 'cookies': 'cookie', 'pastries': 'pastry',
    'jellies': 'jelly', 'candies': 'candy', 'batteries': 'battery',
    'wipes': 'wipe', 'cloths': 'cloth', 'spices': 'spice', 'peppers': 'pepper',
    'greens': 'green', 'chips': 'chip', 'crisps': 'crisp', 'eggs': 'egg',
    'seeds': 'seed', 'cups': 'cup', 'plates': 'plate', 'bowls': 'bowl',
    'bags': 'bag', 'rolls': 'roll', 'buns': 'bun', 'nuts': 'nut',
    'peanuts': 'peanut', 'almonds': 'almond', 'cashews': 'cashew',
    'walnuts': 'walnut', 'pistachios': 'pistachio', 'oats': 'oat',
    'noodles': 'noodle', 'beans': 'bean', 'lentils': 'lentil',
    'peas': 'pea', 'sprouts': 'sprout', 'grapes': 'grape',
    'apples': 'apple', 'bananas': 'banana', 'oranges': 'orange',
    'lemons': 'lemon', 'limes': 'lime', 'onions': 'onion',
    'carrots': 'carrot', 'cucumbers': 'cucumber', 'mushrooms': 'mushroom',
    'crackers': 'cracker', 'vitamins': 'vitamin', 'supplements': 'supplement',
    'pills': 'pill', 'drops': 'drop', 'herbs': 'herb', 'cloves': 'clove',
    'preserves': 'preserve', 'olives': 'olive', 'gloves': 'glove', 'chives': 'chive',
}

def stem_word(w):
    """Normalize English plurals and word inflections to singular root."""
    w = w.lower().strip()
    if not w:
        return ""
    if w in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[w]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ves"):
        return w[:-3] + "f"
    if len(w) > 3 and w.endswith("oes"):
        return w[:-2]
    if len(w) > 4 and (w.endswith("shes") or w.endswith("ches") or w.endswith("xes") or w.endswith("zes") or w.endswith("sses")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w

def stem_phrase(phrase):
    """Stem each individual word token in a phrase."""
    words = re.findall(r'[a-zA-Z0-9]+', phrase.lower())
    return " ".join(stem_word(w) for w in words if w)

# ── Compile matchers ──

def _normalize(name):
    return name.lower().strip()

def _clean_packaging(text):
    """Strip weights, volume, units, pack counts, and container types to reveal core product name."""
    t = text.lower().strip()
    t = re.sub(r'\(.*?\)', ' ', t)
    t = re.sub(r'\[.*?\]', ' ', t)
    t = re.sub(r'\b\d+(\.\d+)?\s*(fl\s*oz|oz|lb|lbs|g|kg|ml|l|liter|liters|gal|gallon|quart|qt|pint|pt|ct|count|pk|pack|cans?|bottles?|rolls?|bags?|boxes?|sprays?|tablets?|capsules?|drops?|pills?|mg|mcg)\b', ' ', t)
    t = re.sub(r'\b(count|pack|pk|bottles?|cans?|bags?|boxes?|rolls?)\b', ' ', t)
    t = re.sub(r'[\s\-#,./\(\)]+$', '', t).strip()
    return ' '.join(t.split())

_global_matchers = None

def get_global_matchers():
    """Return flat list of (keyword, category, keyword_stemmed, is_multiword) sorted by length descending."""
    global _global_matchers
    if _global_matchers is None:
        _global_matchers = []
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                kw_clean = kw.lower().strip()
                kw_stem = stem_phrase(kw_clean)
                is_multi = (" " in kw_clean) or (" " in kw_stem)
                _global_matchers.append((kw_clean, cat, kw_stem, is_multi))
        # Sort so longest phrases match before substrings (e.g. 'shaving cream' before 'cream')
        _global_matchers.sort(key=lambda item: (-len(item[0]), not item[3]))
    return _global_matchers


def _match_kw(kw, text):
    """Check if keyword matches in text either as exact token or substring for longer terms."""
    if len(kw) <= 4 or " " not in kw:
        return bool(re.search(r'\b' + re.escape(kw) + r'\b', text))
    return bool(re.search(r'\b' + re.escape(kw), text)) or (kw in text)


def categorize(name):
    """Return canonical category string or '' for unmatched."""
    if not name or not str(name).strip():
        return ""

    raw_norm = _normalize(str(name))
    stemmed_norm = stem_phrase(str(name))

    # ── Priority 1: Frozen ──
    if "frozen" in raw_norm or "frozen" in stemmed_norm:
        for ice_w in ("ice cream", "gelato", "sorbet", "frozen yogurt", "kulfi", "popsicle"):
            if ice_w in raw_norm or ice_w in stemmed_norm:
                return "Dairy" if ice_w in ("frozen yogurt", "kulfi", "ice cream") else "Snacks & Sweets"
        return "Frozen"

    # ── Priority 2: Canned & Jarred (Word-boundary check, avoiding 'tin' in 'claritin') ──
    if re.search(r'\b(canned|tinned)\b', raw_norm) or re.search(r'\b(canned|tinned)\b', stemmed_norm):
        return "Canned & Jarred"
    if re.search(r'\btin\s+of\b', raw_norm):
        return "Canned & Jarred"

    # ── Priority 3: Produce Overrides ──
    if "spaghetti squash" in raw_norm or "spaghetti squash" in stemmed_norm:
        return "Produce"
    if "curry leaf" in raw_norm or "curry leaves" in raw_norm or "curry leaf" in stemmed_norm:
        return "Produce"
    if "romaine" in raw_norm or "romaine" in stemmed_norm:
        return "Produce"
    if any(w in raw_norm for w in ("fresh basil", "fresh cilantro", "fresh mint", "tender coconut", "spring mix")):
        return "Produce"

    # ── Priority 4: Medicine & Allergy Overrides ──
    if any(re.search(r'\b' + re.escape(med) + r'\b', raw_norm) for med in (
        "claritin", "zyrtec", "allegra", "benadryl", "flonase", "advil", "tylenol",
        "motrin", "aleve", "pepto", "pepto bismol", "tums", "sudafed", "mucinex",
        "robitussin", "dayquil", "nyquil", "nasal spray", "allergy relief", "pain relief"
    )):
        return "Health & Personal Care"

    # ── Priority 5: Head-Noun & Compound Resolution (with packaging cleaned) ──
    cleaned = _clean_packaging(raw_norm)
    cleaned_stemmed = stem_phrase(cleaned)
    tokens = cleaned_stemmed.split()
    last_word = tokens[-1] if tokens else ""
    last_two = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""

    # Seasoning & spice head nouns
    if last_word in ("seasoning", "extract") or last_two in ("seasoning blend", "spice blend"):
        return "Spices & Seasonings"

    # Soup, broth, pasta sauce head nouns
    if last_word in ("soup", "broth", "stock", "bouillon") or last_two in ("pasta sauce", "marinara sauce", "pizza sauce"):
        return "Canned & Jarred"

    # Jam & jelly head nouns
    if last_word in ("jam", "jelly", "preserve", "marmalade"):
        return "Snacks & Sweets"

    # Bakery head nouns
    if last_word in ("bread", "bagel", "croissant", "muffin", "cake", "cupcake", "pastry", "pie", "roti", "naan", "tortilla", "bun", "roll", "loaf"):
        return "Bakery"

    # Beverage head nouns
    if last_word in ("juice", "soda", "lemonade", "smoothie", "tea", "coffee", "latte", "cappuccino", "kombucha", "cider") or last_two in ("energy drink", "soft drink"):
        return "Beverages"

    # Snack head nouns
    if last_word in ("chip", "crisp", "cracker", "popcorn", "cookie", "biscuit", "pretzel"):
        return "Snacks & Sweets"

    # Grains & Cereal head nouns
    if last_word in ("cereal", "cheerios", "granola", "muesli", "oatmeal"):
        return "Legumes & Grains"

    # Vinegar / Oil head nouns
    if last_word in ("vinegar", "oil"):
        if "pasta" in stemmed_norm or "marinara" in stemmed_norm or "tomato" in stemmed_norm:
            return "Canned & Jarred"
        return "Spices & Seasonings"

    # Milk head nouns
    if last_word == "milk" and not any(w in raw_norm for w in ("milk chocolate", "coconut milk canned")):
        return "Dairy"

    # Nut butter head nouns
    if last_two in ("peanut butter", "almond butter", "cashew butter", "sun butter", "sunflower butter", "cookie butter"):
        return "Snacks & Sweets"

    # Meat & Seafood head nouns / cuts
    if last_word in ("thigh", "breast", "wing", "drumstick", "patty", "fillet", "steak") or last_two in ("burger patty", "beef patty"):
        return "Meat & Seafood"

    # ── Priority 6: Dips & Sauces ──
    if "pasta sauce" in raw_norm or "marinara" in raw_norm or "tomato sauce" in raw_norm:
        return "Canned & Jarred"
    if any(w in raw_norm.split() or w in stemmed_norm.split() for w in ("pickle", "achar", "thokku", "chutney", "salsa", "pesto", "tapenade", "hummus", "guacamole", "tzatziki")):
        return "Dips & Spreads"

    # ── Priority 7: Beverages vs Dairy Drinks ──
    is_dairy_drink = any(w in raw_norm or w in stemmed_norm for w in (
        "protein yogurt", "protein yoghurt", "yogurt drink", "lassi",
        "buttermilk", "kefir", "skyr", "milk", "yoghurt drink"
    ))
    if not is_dairy_drink and any(_match_kw(w, raw_norm) or _match_kw(w, stemmed_norm) for w in (
        "juice", "soda", "coke", "pepsi", "sprite", "seltzer",
        "lemonade", "smoothie", "beer", "wine", "liquor", "kombucha",
        "coffee", "tea", "chai", "espresso", "latte", "cappuccino",
        "water", "gatorade", "powerade", "tonic", "ginger ale",
        "coconut water", "soft drink", "cola", "dr pepper",
        "mountain dew", "fanta", "coca", "7up", "root beer", "energy drink"
    )):
        return "Beverages"

    # ── Global Sorted Keyword Matching (Multi-word & Longest first) ──
    matchers = get_global_matchers()

    # 1. Match against cleaned text (packaging and count suffixes stripped)
    if cleaned != raw_norm:
        for kw_clean, cat, kw_stem, is_multi in matchers:
            if _match_kw(kw_clean, cleaned) or _match_kw(kw_stem, cleaned_stemmed):
                return cat

    # 2. Match against full raw and stemmed strings
    for kw_clean, cat, kw_stem, is_multi in matchers:
        if _match_kw(kw_clean, raw_norm) or _match_kw(kw_stem, stemmed_norm) or _match_kw(kw_clean, stemmed_norm):
            return cat

    # ── Fallback Token-Level Check ──
    noise_prefixes = r'^(organic|fresh|raw|pure|natural|all natural|whole|sliced|diced|chopped|shredded|crushed|ground|silken|firm|extra firm|soft|jumbo|large|small|medium|mini|baby|swad|deep|laxmi|patak|kellogg|kelloggs|quaker|nestle|heinz|kraft|trader joe|trader joes|kirkland|great value|365|simple truth|good & gather|v patel & sons inc)\s+'
    stripped_stemmed = re.sub(noise_prefixes, '', cleaned_stemmed).strip()
    if stripped_stemmed != cleaned_stemmed:
        for kw_clean, cat, kw_stem, is_multi in matchers:
            if _match_kw(kw_clean, stripped_stemmed) or _match_kw(kw_stem, stripped_stemmed):
                return cat

    return ""


# ── Gemini AI Helper ──

def _get_gemini_key():
    """Retrieve Gemini API key from environment variables or .env files."""
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
        k = os.environ.get(var, "").strip()
        if k and not k.startswith("dev-") and not k.startswith("secret-"):
            return k

    for path in ["/opt/shared/.env", ".env", "/app/applet/.env"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        for var in ["GEMINI_API_KEY=", "GOOGLE_API_KEY=", "GOOGLE_GENAI_API_KEY="]:
                            if line.strip().startswith(var):
                                k = line.split("=", 1)[1].strip().strip("'").strip('"')
                                if k and not k.startswith("dev-") and not k.startswith("secret-"):
                                    return k
            except Exception:
                pass
    return ""


def categorize_batch_gemini(item_names, api_key=None):
    """Categorize a list of items using Gemini in batches of up to 50 items.
    Validates that returned values belong to CANONICAL_CATEGORIES."""
    if not item_names:
        return {}

    key = api_key or _get_gemini_key()
    if not key:
        return {}

    canonical_str = ", ".join(CANONICAL_CATEGORIES)
    models = [m.strip() for m in os.environ.get(
        "GEMINI_MODEL_NAME",
        "gemini-flash-latest,gemini-3.1-flash-lite-preview,gemini-2.5-flash-lite,gemini-3.1-flash-lite"
    ).split(",") if m.strip()]

    results = {}
    batch_size = 50

    for i in range(0, len(item_names), batch_size):
        batch = item_names[i:i + batch_size]
        prompt = (
            "You are an expert grocery catalog categorizer for ListMate.\n"
            f"Assign each item to EXACTLY ONE of these canonical categories:\n{canonical_str}\n\n"
            f"Items to categorize:\n{json.dumps(batch, indent=2)}\n\n"
            "Return ONLY a valid JSON object mapping each exact item name to its assigned canonical category.\n"
            'Example format: {"Item Name": "Category"}'
        )

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.1,
            }
        }
        data_bytes = json.dumps(body).encode("utf-8")
        parsed_batch = None

        for model in models:
            for api_ver in ("v1beta", "v1"):
                url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={key}"
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={"Content-Type": "application/json"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if text.startswith("```json"):
                            text = text[7:]
                        if text.startswith("```"):
                            text = text[3:]
                        if text.endswith("```"):
                            text = text[:-3]
                        parsed_batch = json.loads(text.strip())
                        break
                except Exception:
                    continue
            if parsed_batch:
                break

        if isinstance(parsed_batch, dict):
            canon_map = {c.lower(): c for c in CANONICAL_CATEGORIES}
            for k, v in parsed_batch.items():
                clean_v = str(v).strip().title()
                if clean_v.lower() in canon_map:
                    results[k] = canon_map[clean_v.lower()]
                elif clean_v in CANONICAL_CATEGORIES:
                    results[k] = clean_v

    return results


# ── 3-Tier Multi-Strategy Auto-Categorization Sweep ──

def backfill_uncategorized_items(use_ai=True, max_ai_items=150):
    """Auto-categorize any existing store_items, list_items, and item_purchase_stats
    in PostgreSQL that currently lack a valid category.

    Execution Pipeline (3-Tier Resolution):
      Tier 1: High-Performance Rule & Head-Noun Categorizer (categorize)
      Tier 2: PostgreSQL Peer Learning (inherit verified categories from other catalog items)
      Tier 3: Batched Gemini AI resolution for remaining uncategorized distinct items
    """
    stats = {
        "store_items_updated": 0,
        "list_items_updated": 0,
        "purchase_stats_updated": 0,
        "tier1_rule_matched": 0,
        "tier2_peer_matched": 0,
        "tier3_gemini_matched": 0,
    }

    db = None
    try:
        import db_pg
        db = db_pg.get_db()

        UNCAT_FILTER = """
            category IS NULL 
            OR TRIM(category) = '' 
            OR LOWER(TRIM(category)) IN ('general', 'uncategorized', 'other', 'none', 'unknown', 'null', 'auto', 'gemini_auto', 'undefined')
        """

        # 1. Fetch uncategorized store_items
        store_rows = db.execute(f"SELECT id, name, household_id, store_id FROM store_items WHERE {UNCAT_FILTER}").fetchall()

        # 2. Fetch uncategorized list_items
        list_rows = db.execute(f"SELECT id, name, household_id, store_id FROM list_items WHERE {UNCAT_FILTER}").fetchall()

        # 3. Fetch uncategorized item_purchase_stats (if table exists)
        stat_rows = []
        try:
            stat_rows = db.execute(f"SELECT household_id, name FROM item_purchase_stats WHERE {UNCAT_FILTER}").fetchall()
        except Exception:
            pass

        total_uncat_rows = len(store_rows) + len(list_rows) + len(stat_rows)
        if total_uncat_rows == 0:
            return stats

        # Collect unique item names
        distinct_names = set()
        for r in store_rows:
            if r.get("name") and str(r["name"]).strip():
                distinct_names.add(str(r["name"]).strip())
        for r in list_rows:
            if r.get("name") and str(r["name"]).strip():
                distinct_names.add(str(r["name"]).strip())
        for r in stat_rows:
            if r.get("name") and str(r["name"]).strip():
                distinct_names.add(str(r["name"]).strip())

        resolved_categories = {}  # norm_name -> canonical category
        name_to_norm = {name: name.lower().strip() for name in distinct_names}

        # ── Tier 1: Local Rule & Head-Noun Matching ──
        for name in distinct_names:
            norm = name_to_norm[name]
            cat = categorize(name)
            if cat and cat in CANONICAL_CATEGORIES:
                resolved_categories[norm] = cat
                stats["tier1_rule_matched"] += 1

        # ── Tier 2: Database Peer Catalog Learning ──
        unresolved_norms = {norm for norm in name_to_norm.values() if norm not in resolved_categories}
        if unresolved_norms:
            try:
                peer_query = """
                    SELECT LOWER(TRIM(name)) AS norm_name, category, COUNT(*) as cnt
                    FROM (
                        SELECT name, category FROM store_items 
                        WHERE category IS NOT NULL AND TRIM(category) != '' 
                          AND LOWER(TRIM(category)) NOT IN ('general', 'uncategorized', 'other', 'none', 'unknown', 'null', 'auto', 'gemini_auto', 'undefined')
                        UNION ALL
                        SELECT name, category FROM list_items 
                        WHERE category IS NOT NULL AND TRIM(category) != '' 
                          AND LOWER(TRIM(category)) NOT IN ('general', 'uncategorized', 'other', 'none', 'unknown', 'null', 'auto', 'gemini_auto', 'undefined')
                    ) catalog
                    WHERE LOWER(TRIM(name)) IS NOT NULL AND TRIM(name) != ''
                    GROUP BY LOWER(TRIM(name)), category
                    ORDER BY cnt DESC
                """
                peer_rows = db.execute(peer_query).fetchall()
                for pr in peer_rows:
                    p_norm = (pr.get("norm_name") or "").strip()
                    p_cat = (pr.get("category") or "").strip()
                    if p_norm in unresolved_norms and p_norm not in resolved_categories and p_cat in CANONICAL_CATEGORIES:
                        resolved_categories[p_norm] = p_cat
                        stats["tier2_peer_matched"] += 1
            except Exception as pe:
                print(f"[categorize] Peer learning query notice: {pe}")

        # ── Tier 3: Batched Gemini AI Fallback ──
        unresolved_names = [name for name in distinct_names if name_to_norm[name] not in resolved_categories]
        if unresolved_names and use_ai:
            api_key = _get_gemini_key()
            if api_key:
                items_to_ai = unresolved_names[:max_ai_items]
                try:
                    ai_results = categorize_batch_gemini(items_to_ai, api_key=api_key)
                    for item_name, cat in ai_results.items():
                        norm = item_name.lower().strip()
                        if cat in CANONICAL_CATEGORIES:
                            resolved_categories[norm] = cat
                            stats["tier3_gemini_matched"] += 1
                except Exception as ae:
                    print(f"[categorize] Gemini AI sweep notice: {ae}")

        # ── Apply Category Updates to Database ──

        # 1. Update store_items
        for r in store_rows:
            name = str(r.get("name") or "").strip()
            norm = name.lower()
            cat = resolved_categories.get(norm)
            if not cat:
                cat = resolved_categories.get(_clean_packaging(norm))
            if cat:
                db.execute("UPDATE store_items SET category = ? WHERE id = ?", (cat, r["id"]))
                stats["store_items_updated"] += 1

        # 2. Update list_items
        for r in list_rows:
            name = str(r.get("name") or "").strip()
            norm = name.lower()
            cat = resolved_categories.get(norm)
            if not cat:
                cat = resolved_categories.get(_clean_packaging(norm))
            if cat:
                db.execute("UPDATE list_items SET category = ? WHERE id = ?", (cat, r["id"]))
                stats["list_items_updated"] += 1

        # 3. Update item_purchase_stats
        for r in stat_rows:
            name = str(r.get("name") or "").strip()
            norm = name.lower()
            cat = resolved_categories.get(norm)
            if not cat:
                cat = resolved_categories.get(_clean_packaging(norm))
            if cat and r.get("household_id") is not None:
                try:
                    db.execute("UPDATE item_purchase_stats SET category = ? WHERE household_id = ? AND name = ?", (cat, r["household_id"], r["name"]))
                    stats["purchase_stats_updated"] += 1
                except Exception:
                    pass

        db.commit()
    except Exception as e:
        print(f"[categorize] Error running backfill_uncategorized_items: {e}")
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    return stats


# ── Tests & Standalone Execution ──
if __name__ == "__main__":
    if "--backfill" in sys.argv or "--sweep" in sys.argv:
        print("[categorize] Starting manual auto-categorization sweep...")
        result = backfill_uncategorized_items()
        print(f"[categorize] Backfill sweep complete: {result}")
        sys.exit(0)

    tests = [
        ("Toothpaste", "Household"),
        ("A2 Milk", "Dairy"),
        ("Egg", "Dairy"),
        ("Eggs", "Dairy"),
        ("Egg Whites", "Dairy"),
        ("Onion", "Produce"),
        ("Spinach", "Produce"),
        ("Avocado", "Produce"),
        ("Bread", "Bakery"),
        ("Hummus", "Dips & Spreads"),
        ("Chickpea", "Legumes & Grains"),
        ("Toor Dal", "Legumes & Grains"),
        ("Basmati Rice", "Legumes & Grains"),
        ("Turmeric Powder", "Spices & Seasonings"),
        ("Cumin", "Spices & Seasonings"),
        ("Olive Oil", "Spices & Seasonings"),
        ("Oil", "Spices & Seasonings"),
        ("Frozen Peas", "Frozen"),
        ("Ice Cream", "Dairy"),
        ("Dish Soap", "Household"),
        ("Paper Towel", "Household"),
        ("Lemon", "Produce"),
        ("Almond", "Nuts & Seeds"),
        ("Cashew", "Nuts & Seeds"),
        ("Canned Tomato", "Canned & Jarred"),
        ("Soy Sauce", "Spices & Seasonings"),
        ("Protein Yogurt Drink", "Dairy"),
        ("Green Beans", "Produce"),
        ("Mouth Wash", "Household"),
        ("Steelcut Oats", "Legumes & Grains"),
        ("Cilantro", "Produce"),
        ("Dosa Batter", "Indian Specialties"),
        ("Idli Podi", "Indian Specialties"),
        ("Mango Pickle", "Dips & Spreads"),
        ("Coconut", "Produce"),
        ("Ghee", "Dairy"),
        ("Frozen Paratha", "Frozen"),
        ("Lays Chips", "Snacks & Sweets"),
        ("Chips", "Snacks & Sweets"),
        ("Coca Cola", "Beverages"),
        ("Orange Juice", "Beverages"),
        ("Naan", "Bakery"),
        ("Jaggery", "Indian Specialties"),
        ("Rajma", "Legumes & Grains"),
        ("Pasta Sauce", "Canned & Jarred"),
        ("Vanilla Extract", "Spices & Seasonings"),
        ("Ziploc Bags", "Household"),
        ("Shampoo", "Household"),
        ("Cheddar Cheese", "Dairy"),
        ("Salsa", "Dips & Spreads"),
        ("Tortilla Chips", "Snacks & Sweets"),
        ("Green pepper", "Produce"),
        ("Green Peppers", "Produce"),
        ("Tofu", "Produce"),
        ("tofu", "Produce"),
        ("Silken Tofu", "Produce"),
        ("Psyllium Husk", "Health & Personal Care"),
        ("Kelloggs Berries cereal", "Legumes & Grains"),
        ("Cherries", "Produce"),
        ("Fresh basil leaves", "Produce"),
        ("Carrot", "Produce"),
        ("Lizol", "Household"),
        ("berries", "Produce"),
        ("Berries", "Produce"),
        ("Coriander seeds", "Spices & Seasonings"),
        ("Optifiber", "Health & Personal Care"),
        ("Oxiclean", "Household"),
        ("Curry leaves", "Produce"),
        ("Curry Leaves", "Produce"),
        ("Zena Super Greens Powder", "Health & Personal Care"),
        ("Stain remover", "Household"),
        ("Reusable cups", "Household"),
        ("Strawberries", "Produce"),
        ("Blueberries", "Produce"),
        ("V Patel & Sons Inc Swad, Jumbo Peanuts", "Nuts & Seeds"),
        ("Shaving cream", "Household"),
        ("PANEER", "Dairy"),
        ("Test", ""),
        ("Unknown Gourmet Item", ""),
        # ── Extended Tricky Real-World Cases ──
        ("Claritin 24 Hour Allergy", "Health & Personal Care"),
        ("Flonase Allergy Relief Nasal Spray", "Health & Personal Care"),
        ("Bonne Maman Strawberry Preserves 13 oz", "Snacks & Sweets"),
        ("Campbell Condensed Tomato Soup", "Canned & Jarred"),
        ("Chicken Noodle Soup", "Canned & Jarred"),
        ("Swanson Chicken Broth 32 oz", "Canned & Jarred"),
        ("Trader Joe Everything But The Bagel Sesame Seasoning Blend", "Spices & Seasonings"),
        ("Spaghetti Squash", "Produce"),
        ("Red Bull Energy Drink", "Beverages"),
        ("Oreos Double Stuf", "Snacks & Sweets"),
        ("Romaine Hearts 3 pack", "Produce"),
        ("Impossible Burger Ground", "Meat & Seafood"),
        ("Beyond Meat Beyond Burger", "Meat & Seafood"),
        ("Garlic Bread", "Bakery"),
        ("Banana Bread", "Bakery"),
        ("Apple Pie", "Bakery"),
        ("Pumpkin Pie", "Bakery"),
        ("Grape Juice", "Beverages"),
        ("Lemon Soda", "Beverages"),
        ("Strawberry Jam", "Snacks & Sweets"),
        ("Almond Butter", "Snacks & Sweets"),
        ("Foster Farms Fresh Chicken Thighs 3 lb", "Meat & Seafood"),
        ("Silk Pure Almond Milk Unsweetened", "Dairy"),
        ("Rao Homemade Marinara Pasta Sauce 24 oz", "Canned & Jarred"),
        ("Dawn Platinum Dishwashing Foam 16 fl oz", "Household"),
        ("Charmin Ultra Soft Bath Tissue 12 Mega Rolls", "Household"),
        ("Swad Idli Rava 5 lb", "Indian Specialties"),
    ]

    print("Running categorize tests...")
    ok = 0
    failed = []
    for name, expected in tests:
        result = categorize(name)
        if result == expected:
            ok += 1
        else:
            failed.append((name, expected, result))

    print(f"\n{ok}/{len(tests)} passed")
    if failed:
        print("Failed tests:")
        for name, expected, got in failed:
            print(f"  ❌ {name:40} Expected: '{expected}', Got: '{got}'")
        sys.exit(1)
    else:
        print("All test cases passed successfully! ✅")
