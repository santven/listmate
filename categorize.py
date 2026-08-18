#!/usr/bin/env python3
"""Auto-categorize grocery items by keyword matching.
Comprehensive mapping covering Western + Indian grocery items.
Loaded once at startup, queried at insert time."""

import re
import os
import json

CATEGORY_KEYWORDS = {
    # ── Meat & Seafood ──
    "Meat & Seafood": [
        "chicken", "poultry", "turkey", "duck", "beef", "steak", "ground beef",
        "pork", "pork chop", "bacon", "sausage", "ham", "lamb", "mutton", "goat",
        "salmon", "tuna", "fish", "tilapia", "cod", "halibut", "trout", "mahi mahi",
        "shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop",
        "squid", "calamari", "anchovy", "sardine", "meatball", "hot dog", "frankfurter",
    ],
    # ── Deli ──
    "Deli": [
        "deli", "deli turkey", "deli ham", "roast beef", "salami", "prosciutto",
        "pepperoni", "bologna", "pastrami", "rotisserie chicken", "cold cut",
        "prepared meal", "potato salad", "cole slaw", "macaroni salad",
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
        "cough syrup", "antacid", "tums", "pepto", "electrolyte powder",
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
        "evaporated milk", "lactose free milk", "a2 milk",
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
        "vermicelli", "sevai", "rice noodle", "somen", "udon",
        "sabudana", "sago", "tapioca", "arrowroot",
        "poha", "flattened rice", "chivda", "murmura", "puffed rice",
        "corn meal", "polenta", "grits", "cornflour", "cornstarch",
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
        "canned", "can ", "tinned", "tin ", "canned tomato", "canned bean",
        "canned corn", "canned tuna", "canned soup", "canned fruit",
        "coconut cream", "jarred", "jar ",
        "pasta sauce", "marinara", "tomato sauce", "tomato paste",
        "artichoke heart", "olive", "caper", "sundried tomato",
        "roasted red pepper", "pickled", "gherkin",
        "sauerkraut", "kimchi", "bamboo shoot",
        "baby corn", "curry paste", "thai paste", "red curry",
        "green curry", "miso", "doenjang", "gochujang",
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
    'pills': 'pill', 'drops': 'drop', 'herbs': 'herb', 'cloves': 'clove'
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
    """Return category string or '' for unmatched."""
    if not name or not name.strip():
        return ""

    raw_norm = _normalize(name)
    stemmed_norm = stem_phrase(name)

    # ── Priority 1: Frozen ──
    if "frozen" in raw_norm or "frozen" in stemmed_norm:
        for ice_w in ("ice cream", "gelato", "sorbet", "frozen yogurt", "kulfi", "popsicle"):
            if ice_w in raw_norm or ice_w in stemmed_norm:
                return "Dairy" if ice_w in ("frozen yogurt", "kulfi", "ice cream") else "Snacks & Sweets"
        return "Frozen"

    # ── Priority 2: Canned & Jarred ──
    if any(w in raw_norm for w in ("canned", "canned ", "tinned", "tin ")) or any(w in stemmed_norm for w in ("canned", "tinned")):
        return "Canned & Jarred"

    # ── Priority 3: Dips & Sauces ──
    if "pasta sauce" in raw_norm or "marinara" in raw_norm or "tomato sauce" in raw_norm:
        return "Canned & Jarred"
    if any(w in raw_norm.split() or w in stemmed_norm.split() for w in ("pickle", "achar", "thokku", "chutney", "salsa", "pesto", "tapenade", "hummus", "guacamole", "tzatziki")):
        return "Dips & Spreads"

    # ── Priority 4: Head-noun check (e.g. 'berry cereal' -> Cereal, 'apple cider vinegar' -> Vinegar, 'banana bread' -> Bakery) ──
    last_word = stemmed_norm.split()[-1] if stemmed_norm else ""
    if last_word in ("cereal", "cheerios", "granola", "muesli", "oatmeal"):
        return "Legumes & Grains"
    if last_word in ("bread", "bagel", "croissant", "muffin", "cake", "cupcake", "pastry", "pie", "roti", "naan", "tortilla", "bun", "roll"):
        return "Bakery"
    if last_word in ("chip", "crisp", "cracker", "popcorn", "cookie", "biscuit", "pretzel"):
        return "Snacks & Sweets"
    if last_word in ("juice", "soda", "lemonade", "smoothie", "tea", "coffee", "latte", "cappuccino", "kombucha", "cider"):
        return "Beverages"
    if last_word in ("vinegar", "oil", "salt", "sauce"):
        if "pasta" in stemmed_norm or "marinara" in stemmed_norm or "tomato" in stemmed_norm:
            return "Canned & Jarred"
        return "Spices & Seasonings"

    # ── Priority 5: Beverages vs Dairy Drinks ──
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
        "mountain dew", "fanta", "coca", "7up", "root beer"
    )):
        return "Beverages"

    # ── Global Sorted Keyword Matching (Multi-word & Longest first) ──
    matchers = get_global_matchers()
    for kw_clean, cat, kw_stem, is_multi in matchers:
        if _match_kw(kw_clean, raw_norm) or _match_kw(kw_stem, stemmed_norm) or _match_kw(kw_clean, stemmed_norm):
            return cat

    # ── Fallback Token-Level Check ──
    # Clean leading brand prefixes/noise words and test root words
    noise_prefixes = r'^(organic|fresh|raw|pure|natural|all natural|whole|sliced|diced|chopped|shredded|crushed|ground|silken|firm|extra firm|soft|jumbo|large|small|medium|mini|baby|swad|deep|laxmi|patak|kellogg|kelloggs|quaker|nestle|heinz|kraft|trader joe|trader joes|kirkland|great value|365|simple truth|good & gather|v patel & sons inc)\s+'
    cleaned_stemmed = re.sub(noise_prefixes, '', stemmed_norm).strip()
    if cleaned_stemmed != stemmed_norm:
        for kw_clean, cat, kw_stem, is_multi in matchers:
            if _match_kw(kw_clean, cleaned_stemmed) or _match_kw(kw_stem, cleaned_stemmed):
                return cat

    return ""


def backfill_uncategorized_items():
    """Auto-categorize any existing store_items and list_items in PostgreSQL that currently lack a category."""
    updated_store = 0
    updated_list = 0
    try:
        import db_pg
        db = db_pg.get_db()

        # 1. Update store_items
        store_rows = db.execute("SELECT id, name FROM store_items WHERE category IS NULL OR TRIM(category) = ''").fetchall()
        for r in store_rows:
            cat = categorize(r["name"])
            if cat:
                db.execute("UPDATE store_items SET category = ? WHERE id = ?", (cat, r["id"]))
                updated_store += 1

        # 2. Update list_items
        list_rows = db.execute("SELECT id, name FROM list_items WHERE category IS NULL OR TRIM(category) = ''").fetchall()
        for r in list_rows:
            cat = categorize(r["name"])
            if cat:
                db.execute("UPDATE list_items SET category = ? WHERE id = ?", (cat, r["id"]))
                updated_list += 1

        # 3. Update item_purchase_stats
        stat_rows = db.execute("SELECT household_id, name FROM item_purchase_stats WHERE category IS NULL OR TRIM(category) = ''").fetchall()
        for r in stat_rows:
            cat = categorize(r["name"])
            if cat:
                db.execute("UPDATE item_purchase_stats SET category = ? WHERE household_id = ? AND name = ?", (cat, r["household_id"], r["name"]))

        db.commit()
    except Exception as e:
        print(f"[categorize] Error running backfill_uncategorized_items: {e}")
    return {"store_items_updated": updated_store, "list_items_updated": updated_list}


# ── Tests ──
if __name__ == "__main__":
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
        ("Ice Cream", "Dairy"),  # ice cream is dairy before frozen
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
    ]

    print("Category tests:")
    ok = 0
    for name, expected in tests:
        result = categorize(name)
        status = "✅" if result == expected else f"❌ (expected '{expected}', got '{result}')"
        if result == expected:
            ok += 1
        print(f"  {status:35} {name:38} → {result}")
    print(f"\n{ok}/{len(tests)} passed")
