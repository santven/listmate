#!/usr/bin/env python3
"""Auto-categorize grocery items by keyword matching.
Comprehensive mapping covering Western + Indian grocery items.
Loaded once at startup, queried at insert time."""

import re
import os
import json

CATEGORY_KEYWORDS = {
    # ── Produce: Top-level for produce section ──
    "Produce": [
        # Vegetables
        "onion", "tomato", "potato", "ginger", "garlic", "carrot", "cucumber",
        "spinach", "kale", "lettuce", "arugula", "chard", "collard", "bok choy",
        "broccoli", "cauliflower", "cabbage", "brussels sprout", "asparagus",
        "celery", "bell pepper", "capsicum", "jalapeno", "serrano", "habanero",
        "chili", "chilli", "green bean", "okra", "bhindi", "lady finger",
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
        # Fresh herbs
        "cilantro", "coriander leaf", "mint", "pudina", "basil", "tulsi",
        "curry leaf", "kariveppilai", "dill", "parsley", "rosemary",
        "thyme", "sage", "oregano", "chive", "lemongrass",
        # Fruit
        "apple", "banana", "orange", "grape", "mango", "pineapple",
        "watermelon", "cantaloupe", "honeydew", "melon", "papaya", "guava",
        "pomegranate", "anar", "kiwi", "peach", "plum", "nectarine",
        "apricot", "pear", "cherry", "strawberry", "blueberry", "raspberry",
        "blackberry", "cranberry", "fig", "date", "lychee", "rambutan",
        "dragon fruit", "star fruit", "custard apple", "sitaphal",
        "sapota", "chikoo", "jackfruit", "tender coconut",
        "lemon", "lime", "nimbu", "avocado", "coconut",
    ],

    # ── Dairy ──
    "Dairy": [
        "milk", "butter", "ghee", "yogurt", "curd", "dahi", "yoghurt",
        "buttermilk", "chaas", "moru", "cream", "sour cream", "half and half",
        "whipped cream", "heavy cream", "cream cheese", "creamcheese",
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
    ],

    # ── Legumes & Grains ──
    "Legumes & Grains": [
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
        "turmeric", "haldi", "cumin", "jeera", "coriander powder",
        "dhania", "chili powder", "red chili", "kashmiri chili",
        "garam masala", "sambar powder", "rasam powder", "curry powder",
        "mustard seed", "rai", "sarson", "fenugreek seed", "methi seed",
        "asafoetida", "hing", "cardamom", "elaichi", "cinnamon", "dalchini",
        "clove", "laung", "black pepper", "kali mirch", "peppercorn",
        "nutmeg", "jaiphal", "mace", "javitri", "star anise",
        "bay leaf", "tej patta", "fennel seed", "saunf",
        "carom seed", "ajwain", "nigella seed", "kalonji",
        "poppy seed", "khus khus", "sesame seed", "til",
        "tamarind", "imli", "kokum", "amchur", "dry mango powder",
        "chaat masala", "pav bhaji masala", "chole masala",
        "biryani masala", "tandoori masala", "kitchen king",
        "salt", "pink salt", "black salt", "kala namak", "sea salt",
        "vanilla extract", "vanilla essence", "baking powder",
        "baking soda", "yeast", "gelatin", "agar agar",
        "cocoa powder", "chocolate chip", "sprinkle",
        "oregano", "italian seasoning", "paprika", "cayenne",
        "five spice", "szechuan", "soy sauce", "vinegar",
        "balsamic", "apple cider vinegar", "rice vinegar",
        "worcestershire", "fish sauce", "oyster sauce",
        "olive oil", "vegetable oil", "canola oil", "sunflower oil",
        "coconut oil", "sesame oil", "mustard oil", "peanut oil",
        "cooking spray", "pam", "avocado oil", "grapeseed oil",
    ],

    # ── Snacks & Sweets ──
    "Snacks & Sweets": [
        "chip", "crisp", "cheeto", "dorito", "tortilla chip", "nacho",
        "pretzel", "popcorn", "cracker", "rice cake", "granola bar",
        "protein bar", "energy bar", "candy", "chocolate", "gummy",
        "cookie", "biscuit", "wafer", "namkeen", "bhujia", "sev",
        "mixture", "chakli", "murukku", "khakhra", "chivda",
        "samosa", "pakora", "vada", "khaman", "dhokla",
        "halwa", "laddu", "ladoo", "barfi", "burfi", "jalebi",
        "gulab jamun", "rasgulla", "peda", "kaju katli", "mysore pak",
        "soan papdi", "petha", "sandesh", "kheer mix", "ice cream",
        "gelato", "sorbet", "frozen yogurt", "popsicle", "kulfi",
        "falooda", "cake mix", "brownie mix", "pancake mix",
        "jam", "jelly", "marmalade", "preserve", "honey",
        "maple syrup", "agave", "chocolate syrup", "caramel",
        "peanut butter", "almond butter", "cashew butter", "nutella",
        "protein powder", "whey", "creatine", "bcaa", "pre workout",
    ],

    # ── Beverages ──
    "Beverages": [
        "coffee", "tea", "chai", "espresso", "latte", "cappuccino",
        "green tea", "black tea", "herbal tea", "matcha", "chai patti",
        "water", "sparkling water", "soda", "seltzer", "club soda",
        "tonic", "juice", "orange juice", "apple juice", "cranberry juice",
        "lemonade", "smoothie", "milkshake", "protein shake",
        "coconut water", "buttermilk", "lassi",
        "soft drink", "coke", "pepsi", "sprite", "ginger ale",
        "kombucha", "beer", "wine", "liquor", "spirit",
        "almond milk", "soy milk", "oat milk", "coconut milk",
        "electrolyte", "gatorade", "powerade", "pedia",
    ],

    # ── Frozen ──
    "Frozen": [
        "frozen", "freezer", "ice cream", "frozen vegetable", "frozen fruit",
        "frozen pizza", "frozen dinner", "frozen meal", "frozen paratha",
        "frozen naan", "frozen roti", "frozen paneer", "frozen samosa",
        "frozen peas", "frozen corn", "frozen spinach", "frozen okra",
        "frozen bhindi", "frozen mixed vegetable",
        "frozen berry", "frozen mango", "frozen coconut",
        "ice cube", "frozen waffle", "frozen french fry", "tater tot",
    ],

    # ── Household ──
    "Household": [
        "toothpaste", "toothbrush", "floss", "mouthwash", "mouth wash",
        "shampoo", "conditioner", "body wash", "soap", "hand soap",
        "dish soap", "dishwasher", "detergent", "laundry", "fabric softener",
        "bleach", "cleaner", "cleaning", "wipe", "disinfectant",
        "paper towel", "tissue", "toilet paper", "kleenex", "napkin",
        "trash bag", "garbage bag", "ziploc", "foil", "aluminum foil",
        "plastic wrap", "cling wrap", "parchment paper", "wax paper",
        "sponge", "scrub", "broom", "mop", "duster", "glove",
        "battery", "light bulb", "air freshener", "candle",
        "hand sanitizer", "sanitizer", "lotion", "sunscreen", "sunscreen",
        "deodorant", "razor", "shaving", "tampon", "pad", "diaper", "wipe",
        "toothpaste", "toothbrush", "dental", "mouth wash", "mouthwash",
        "cotton ball", "cotton swab", "q tip", "band aid", "bandaid",
        "first aid", "medicine", "vitamin", "supplement", "pill",
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
        "coconut cream", "coconut milk", "jarred", "jar ",
        "pasta sauce", "marinara", "tomato sauce", "tomato paste",
        "artichoke heart", "olive", "caper", "sundried tomato",
        "roasted red pepper", "pickle", "pickled", "gherkin",
        "sauerkraut", "kimchi", "bamboo shoot", "water chestnut",
        "baby corn", "curry paste", "thai paste", "red curry",
        "green curry", "miso", "doenjang", "gochujang",
    ],

    # ── Nuts & Seeds ──
    "Nuts & Seeds": [
        "almond", "cashew", "walnut", "pecan", "pistachio", "macadamia",
        "brazil nut", "hazelnut", "pine nut", "peanut", "mungfali",
        "sunflower seed", "pumpkin seed", "chia seed", "flax seed",
        "hemp seed", "hemp heart", "sesame seed", "til", "poppy seed",
        "khus khus", "watermelon seed", "muskmelon seed",
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
        "poriyal", "thoran", "kootu", "pachadi", "raita",
        "papad", "appalam", "vadam", "vathal", "fryum",
        "moringa powder", "drumstick leaf powder", "sathu maavu",
        "health mix", "kanji", "porridge", "ragi malt",
        "pani puri", "golgappa", "sev puri", "bhel puri", "dahi puri",
        "pani puri kit", "chaat kit", "chaat", "pani",
        "ghee", "nei", "jaggery", "gud", "vellam",
        "coconut", "nariyal", "thengai", "desiccated coconut",
        "kobbari", "copra", "grated coconut", "coconut milk powder",
        "kolam", "jaggery", "sugar candy", "kalkandu", "palm sugar",
        "vathakuzhambu", "kara kuzhambu", "puli kuzhambu",
        "molagai podi", "gunpowder", "idli podi", "milagai podi",
    ],
}

# ── Compile matchers ──

def _normalize(name):
    return name.lower().strip()

_compiled = None

def get_matchers():
    """Return list of (category, pattern_list). Lazily compiled."""
    global _compiled
    if _compiled is None:
        _compiled = []
        for cat, keywords in CATEGORY_KEYWORDS.items():
            # Sort by length desc so "frozen yogurt" matches before "yogurt"
            patterns = []
            for kw in sorted(keywords, key=lambda x: -len(x)):
                patterns.append(kw)  # keep as plain string
            _compiled.append((cat, patterns))
    return _compiled


def categorize(name):
    """Return category string or '' for unmatched."""
    name = _normalize(name)

    # Strip common prefixes that don't help matching
    name_stripped = re.sub(r'^organic\s+', '', name)

    # ── Priority rules: check frozen/canned/beverage prefixes first ──
    if any(w in name_stripped for w in ("frozen",)):
        # Check if it's a frozen dessert (ice cream etc)
        for ice_w in ("ice cream", "gelato", "sorbet", "frozen yogurt", "kulfi", "popsicle"):
            if ice_w in name_stripped:
                return "Dairy" if ice_w in ("frozen yogurt", "kulfi") else "Snacks & Sweets"
        return "Frozen"

    if any(w in name_stripped for w in ("canned", "canned ", "tin ", "tinned")):
        # Check if canned fruit/veg → still Canned
        return "Canned & Jarred"

    # Beverage-specific keywords check before produce/juice confusion
    # But NOT if it's a dairy/protein drink
    is_dairy_drink = any(w in name_stripped for w in ("protein yogurt", "protein yoghurt", "yogurt drink",
        "lassi", "buttermilk", "kefir", "skyr", "probiotic", "milk", "yoghurt drink"))
    if not is_dairy_drink and any(w in name_stripped for w in ("juice", "soda", "coke", "pepsi", "sprite", "seltzer",
        "lemonade", "smoothie", "beer", "wine", "liquor", "kombucha",
        "coffee", "tea", "chai", "espresso", "latte", "cappuccino",
        "water", "gatorade", "powerade", "tonic", "ginger ale",
        "coconut water", "sambar", "protein shake",
        "electrolyte", "soft drink", "cola", "pepsi", "coke", "dr pepper",
        "mountain dew", "fanta", "sprite", "coca", "7up", "root beer")):
        return "Beverages"

    # Tortilla chips → Snacks (not bakery — tortilla alone is bakery)
    if "tortilla chip" in name_stripped or "tortilla crisps" in name_stripped:
        return "Snacks & Sweets"

    # Pasta sauce → Canned (not legumes from "pasta")
    if "pasta sauce" in name_stripped or "marinara" in name_stripped or "tomato sauce" in name_stripped:
        return "Canned & Jarred"

    # "pickle" / "achar" as in Indian pickles → Dips & Spreads (not produce)
    if any(w in name_stripped for w in ("pickle", "achar", "thokku",
        "chutney", "jam", "jelly", "marmalade", "preserve",
        "salsa", "pesto", "tapenade")):
        return "Dips & Spreads"

    for cat, keywords in get_matchers():
        for kw in keywords:
            if kw in name_stripped:
                return cat
    return ""


# ── Tests ──
if __name__ == "__main__":
    tests = [
        ("Toothpaste", "Household"),
        ("A2 Milk", "Dairy"),
        ("Egg", "Dairy"),
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
        ("Unknown Gourmet Item", ""),
    ]

    print("Category tests:")
    ok = 0
    for name, expected in tests:
        result = categorize(name)
        status = "✅" if result == expected else f"❌ (got '{result}')"
        if result == expected:
            ok += 1
        print(f"  {status:20} {name:30} → {result}")
    print(f"\n{ok}/{len(tests)} passed")
