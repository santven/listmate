// Daily Culinary Wisdom & Inspiration Engine for ListMate
// Issue #386: Curated proverbs, Thirukkural, culinary masters & time-of-day greetings

(function(global) {
  var window = typeof window !== 'undefined' ? window : global;
  'use strict';

  var CULINARY_QUOTES = [
  {
    "id": "kural-942",
    "category": "Thirukkural",
    "theme": "Diet & Digestion",
    "text": "No medicine is needed for the body if one eats with moderation only after previous food is digested.",
    "original_text": "மருந்தென வேண்டாவாம் யாக்கைக்கு அருந்தியது அற்றது போற்றி உணின்",
    "author": "Thirukkural 942",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-944",
    "category": "Thirukkural",
    "theme": "Mindful Dining",
    "text": "Eat wholesome food in mindful measure; your life will be long and free of distress.",
    "original_text": "மாறுபாடு இல்லாத உண்டி மறுத்துண்ணின் ஊறுபாடு இல்லை உயிர்க்கு",
    "author": "Thirukkural 944",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-943",
    "category": "Thirukkural",
    "theme": "Longevity & Health",
    "text": "Eat with measure and appreciation; that is the path to longevity and vitality.",
    "original_text": "அற்றால் அளவறிந்து உண்க அஃதுடம்பு பெற்றான் நெடிதுய்க்கும் ஆறு",
    "author": "Thirukkural 943",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-81",
    "category": "Thirukkural",
    "theme": "Gracious Hospitality",
    "text": "The true purpose of maintaining a home is to cook with love and welcome guests with warmth.",
    "original_text": "இருந்தோம்பி இல்வாழ்வ தெல்லாம் விருந்தோம்பி வேளாண்மை செய்தற் பொருட்டு",
    "author": "Thirukkural 81",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-84",
    "category": "Thirukkural",
    "theme": "Joy at the Table",
    "text": "Good fortune and happiness joyfully reside in the home where meals are shared with a welcoming smile.",
    "original_text": "அகனமர்ந்து செய்யாள் உறையும் முகனமர்ந்து நல்விருந்து ஓம்புவான் இல்",
    "author": "Thirukkural 84",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-1031",
    "category": "Thirukkural",
    "theme": "Earth & Harvest",
    "text": "Though the world turns through endless trades, it always depends on the plow and the harvest.",
    "original_text": "சுழன்றும்ஏர்ப் பின்னது உலகம் அதனால் உழந்தும் உழவே தலை",
    "author": "Thirukkural 1031",
    "era": "Classical Tamil"
  },
  {
    "id": "kural-1032",
    "category": "Thirukkural",
    "theme": "Nourishing the World",
    "text": "Those who nurture crops and feed the world are the true linchpin of life.",
    "original_text": "உழுவார் உலகத்தார்க்கு ஆணிஅஃது ஆற்றாது எழுவாரை எல்லாம் பொறுத்து",
    "author": "Thirukkural 1032",
    "era": "Classical Tamil"
  },
  {
    "id": "tamil-proverb-1",
    "category": "Tamil Wisdom",
    "theme": "Care & Flavor",
    "text": "Salt gives taste to food, but love gives taste to life.",
    "original_text": "உப்பில்லா பண்டம் குப்பையிலே",
    "author": "Tamil Proverb",
    "era": "Traditional Wisdom"
  },
  {
    "id": "upanishad-1",
    "category": "Indian Wisdom",
    "theme": "Sacred Nourishment",
    "text": "Food is the divine source of life, health, and vitality.",
    "original_text": "अन्नं ब्रह्म — Annam Brahma",
    "author": "Taittiriya Upanishad",
    "era": "Ancient Sanskrit"
  },
  {
    "id": "sanskrit-1",
    "category": "Indian Wisdom",
    "theme": "Hospitality",
    "text": "To feed a guest with love and warmth is to honor the divine.",
    "original_text": "अतिथिदेवो भव — Atithi Devo Bhava",
    "author": "Ancient Sanskrit Maxim",
    "era": "Traditional"
  },
  {
    "id": "ayurveda-1",
    "category": "Ayurveda",
    "theme": "Holistic Health",
    "text": "When diet is wrong, medicine is of no use. When diet is correct, medicine is of no need.",
    "original_text": "हितभुक् मितभुक् — Hitabhuk Mitabhuk",
    "author": "Ayurvedic Wisdom",
    "era": "Traditional Medicine"
  },
  {
    "id": "ayurveda-2",
    "category": "Ayurveda",
    "theme": "Healing Care",
    "text": "The best medicine in the world is a hot, freshly cooked meal made with care and patience.",
    "original_text": null,
    "author": "Ayurvedic Proverb",
    "era": "Traditional"
  },
  {
    "id": "hindi-saying-1",
    "category": "Indian Wisdom",
    "theme": "Daily Balance",
    "text": "First nourish the body with good food, then attend to the work of the world.",
    "original_text": "पेट पूजा पहले, काम दूजा",
    "author": "Indian Saying",
    "era": "Traditional"
  },
  {
    "id": "bengali-saying-1",
    "category": "Indian Wisdom",
    "theme": "Comfort of Home",
    "text": "Hot rice, golden ghee, and comforting dal: the three quiet treasures of a happy home.",
    "original_text": null,
    "author": "Indian Tradition",
    "era": "Traditional"
  },
  {
    "id": "south-indian-1",
    "category": "Indian Wisdom",
    "theme": "Morning Ritual",
    "text": "Filter coffee in the morning is not merely a beverage; it is an awakening of the soul.",
    "original_text": null,
    "author": "South Indian Tradition",
    "era": "Traditional"
  },
  {
    "id": "sanjeev-kapoor-1",
    "category": "Indian Cuisine",
    "theme": "Alchemy of Spices",
    "text": "Indian cooking is a symphony of spices where every single note has a healing purpose.",
    "original_text": null,
    "author": "Chef Sanjeev Kapoor",
    "era": "Culinary Master"
  },
  {
    "id": "vikas-khanna-1",
    "category": "Indian Cuisine",
    "theme": "Memory & Culture",
    "text": "Food is not just calories; it is memory, culture, and love served on a plate.",
    "original_text": null,
    "author": "Chef Vikas Khanna",
    "era": "Michelin Star Chef"
  },
  {
    "id": "madhur-jaffrey-1",
    "category": "Indian Cuisine",
    "theme": "Soul of Spices",
    "text": "Spices are not just for heat; they are for depth, perfume, and soul.",
    "original_text": null,
    "author": "Madhur Jaffrey",
    "era": "Culinary Author"
  },
  {
    "id": "tarla-dalal-1",
    "category": "Indian Cuisine",
    "theme": "Kitchen Music",
    "text": "In an Indian kitchen, the tadka is the applause that welcomes the spices into the dish.",
    "original_text": null,
    "author": "Tarla Dalal",
    "era": "Culinary Icon"
  },
  {
    "id": "ranveer-brar-1",
    "category": "Indian Cuisine",
    "theme": "Everyday Comfort",
    "text": "A dish prepared with the right temper of mustard seeds and fresh curry leaves brings instant comfort.",
    "original_text": null,
    "author": "Chef Ranveer Brar",
    "era": "Master Chef"
  },
  {
    "id": "floyd-cardoz-1",
    "category": "Indian Cuisine",
    "theme": "Patience & Heat",
    "text": "The secret of great cooking is understanding how gentle heat releases the sweetness in slow-cooked spices.",
    "original_text": null,
    "author": "Chef Floyd Cardoz",
    "era": "Culinary Pioneer"
  },
  {
    "id": "vikas-khanna-2",
    "category": "Indian Cuisine",
    "theme": "Roots & Heritage",
    "text": "Food connects us to our roots and brings warmth to the table no matter where we are in the world.",
    "original_text": null,
    "author": "Chef Vikas Khanna",
    "era": "Author & Filmmaker"
  },
  {
    "id": "escoffier-1",
    "category": "French Gastronomy",
    "theme": "Foundation of Happiness",
    "text": "Good food is the foundation of genuine happiness.",
    "original_text": "La bonne cuisine est la base du véritable bonheur.",
    "author": "Auguste Escoffier",
    "era": "Father of Modern Cuisine"
  },
  {
    "id": "savarin-1",
    "category": "French Gastronomy",
    "theme": "Identity & Dining",
    "text": "Tell me what you eat, and I will tell you what you are.",
    "original_text": "Dis-moi ce que tu manges, je te dirai ce que tu es.",
    "author": "Jean Anthelme Brillat-Savarin",
    "era": "Physiology of Taste (1825)"
  },
  {
    "id": "savarin-2",
    "category": "French Gastronomy",
    "theme": "Joy of the Table",
    "text": "A meal without wine is like a day without sunshine.",
    "original_text": "Un repas sans vin est comme une journée sans soleil.",
    "author": "Jean Anthelme Brillat-Savarin",
    "era": "Classical French"
  },
  {
    "id": "french-proverb-1",
    "category": "French Gastronomy",
    "theme": "Friendship",
    "text": "Good cuisine and good wine are the true secrets of lasting friendships.",
    "original_text": "Bonne cuisine et bon vin font les bons amis.",
    "author": "French Proverb",
    "era": "Traditional"
  },
  {
    "id": "bocuse-1",
    "category": "French Gastronomy",
    "theme": "Purity of Cooking",
    "text": "Classic or modern, there is only one true cuisine: good cuisine.",
    "original_text": "Classique ou moderne, il n'y a qu'une seule cuisine... la bonne.",
    "author": "Paul Bocuse",
    "era": "Chef of the Century"
  },
  {
    "id": "rabelais-1",
    "category": "French Gastronomy",
    "theme": "Appetite",
    "text": "Appetite comes with the first delicious bite.",
    "original_text": "L'appétit vient en mangeant.",
    "author": "François Rabelais",
    "era": "French Renaissance"
  },
  {
    "id": "pepin-1",
    "category": "French Gastronomy",
    "theme": "Simplicity",
    "text": "Cooking is not difficult. Everyone has taste, even if they do not realize it.",
    "original_text": null,
    "author": "Jacques Pépin",
    "era": "Master Chef"
  },
  {
    "id": "larochefoucauld-1",
    "category": "Philosophers & Thinkers",
    "theme": "Mindful Eating",
    "text": "To eat is a necessity, but to eat intelligently is an art.",
    "original_text": "Manger est une nécessité, mais manger intelligemment est un art.",
    "author": "François de La Rochefoucauld",
    "era": "1665"
  },
  {
    "id": "italian-proverb-1",
    "category": "Italian Conviviality",
    "theme": "Ageless Gathering",
    "text": "At the table with good friends and family, nobody ever grows old.",
    "original_text": "A tavola non si invecchia.",
    "author": "Italian Proverb",
    "era": "Traditional"
  },
  {
    "id": "fellini-1",
    "category": "Italian Conviviality",
    "theme": "Magic of Pasta",
    "text": "Life is a combination of magic and pasta.",
    "original_text": "La vita è una combinazione di pasta e magia.",
    "author": "Federico Fellini",
    "era": "Italian Master"
  },
  {
    "id": "italian-proverb-2",
    "category": "Italian Conviviality",
    "theme": "Uncounted Joy",
    "text": "Age and glasses of wine should never be counted.",
    "original_text": "Gli anni e i bicchieri di vino non si contano mai.",
    "author": "Italian Proverb",
    "era": "Traditional"
  },
  {
    "id": "italian-saying-1",
    "category": "Italian Conviviality",
    "theme": "Peace of Spirit",
    "text": "Good food warms the heart and brings peace to the spirit.",
    "original_text": "Il buon cibo scalda il cuore e rasserena lo spirito.",
    "author": "Italian Saying",
    "era": "Traditional"
  },
  {
    "id": "italian-proverb-3",
    "category": "Italian Conviviality",
    "theme": "Olive Oil & Passion",
    "text": "Everything tastes better with a drizzle of pure olive oil and genuine passion.",
    "original_text": "Tutto è più buono con un filo d'olio e tanta passione.",
    "author": "Italian Proverb",
    "era": "Traditional"
  },
  {
    "id": "italian-saying-2",
    "category": "Italian Conviviality",
    "theme": "Simple Ingredients",
    "text": "Simple ingredients, great patience, and genuine care make the finest dish.",
    "original_text": "Pochi ingredienti, tanta pazienza e vero amore fanno il piatto migliore.",
    "author": "Italian Culinary Maxim",
    "era": "Traditional"
  },
  {
    "id": "julia-child-1",
    "category": "Culinary Masters",
    "theme": "Lovers of Food",
    "text": "People who love to eat are always the best people.",
    "original_text": null,
    "author": "Julia Child",
    "era": "Culinary Icon"
  },
  {
    "id": "bourdain-1",
    "category": "Culinary Masters",
    "theme": "Generosity & Appetite",
    "text": "Cooking is a craft, but it's also about curiosity, generosity, and appetite.",
    "original_text": null,
    "author": "Anthony Bourdain",
    "era": "Chef & Storyteller"
  },
  {
    "id": "mfk-fisher-1",
    "category": "Culinary Literature",
    "theme": "First Things First",
    "text": "First we eat, then we do everything else.",
    "original_text": null,
    "author": "M.F.K. Fisher",
    "era": "Gastronomic Author"
  },
  {
    "id": "mfk-fisher-2",
    "category": "Culinary Literature",
    "theme": "Baking Comfort",
    "text": "The smell of good bread baking is indescribably comforting.",
    "original_text": null,
    "author": "M.F.K. Fisher",
    "era": "Author"
  },
  {
    "id": "virginia-woolf-1",
    "category": "Philosophers & Writers",
    "theme": "The Well-Dined Life",
    "text": "One cannot think well, love well, sleep well, if one has not dined well.",
    "original_text": null,
    "author": "Virginia Woolf",
    "era": "A Room of One's Own (1929)"
  },
  {
    "id": "tolkien-1",
    "category": "Philosophers & Writers",
    "theme": "Food & Cheer",
    "text": "If more of us valued food and cheer and song above hoarded gold, it would be a merrier world.",
    "original_text": null,
    "author": "J.R.R. Tolkien",
    "era": "The Hobbit"
  },
  {
    "id": "george-bernard-shaw-1",
    "category": "Philosophers & Writers",
    "theme": "Sincere Love",
    "text": "There is no love sincerer than the love of food.",
    "original_text": null,
    "author": "George Bernard Shaw",
    "era": "Playwright & Nobel Laureate"
  },
  {
    "id": "thomas-keller-1",
    "category": "Culinary Masters",
    "theme": "Soul of the Recipe",
    "text": "A recipe has no soul. You, as the cook, must bring soul to the recipe.",
    "original_text": null,
    "author": "Chef Thomas Keller",
    "era": "The French Laundry"
  },
  {
    "id": "alice-waters-1",
    "category": "Culinary Masters",
    "theme": "The Living Table",
    "text": "This is the power of the table: it brings us together and feeds our spirit.",
    "original_text": null,
    "author": "Alice Waters",
    "era": "Farm-to-Table Pioneer"
  },
  {
    "id": "ruth-reichl-1",
    "category": "Culinary Literature",
    "theme": "Endlessly Delicious",
    "text": "Pull up a chair. Take a taste. Come join us. Life is so endlessly delicious.",
    "original_text": null,
    "author": "Ruth Reichl",
    "era": "Food Editor & Author"
  },
  {
    "id": "james-beard-1",
    "category": "Culinary Masters",
    "theme": "Universal Ground",
    "text": "Food is our common ground, a universal experience.",
    "original_text": null,
    "author": "James Beard",
    "era": "Dean of American Cookery"
  },
  {
    "id": "hippocrates-1",
    "category": "Philosophers & Thinkers",
    "theme": "Food as Medicine",
    "text": "Let food be thy medicine and medicine be thy food.",
    "original_text": null,
    "author": "Hippocrates",
    "era": "Ancient Greece (c. 400 BC)"
  },
  {
    "id": "pythagoras-1",
    "category": "Philosophers & Thinkers",
    "theme": "Purity of Salt",
    "text": "Salt is born of the purest parents: the sun and the sea.",
    "original_text": null,
    "author": "Pythagoras",
    "era": "Ancient Philosophy"
  },
  {
    "id": "prudhomme-1",
    "category": "Culinary Masters",
    "theme": "Unpretentious Good Food",
    "text": "You don't need a silver fork to eat good food.",
    "original_text": null,
    "author": "Chef Paul Prudhomme",
    "era": "Cajun & Creole Master"
  },
  {
    "id": "charles-schulz-1",
    "category": "Food Wit",
    "theme": "Chocolate & Love",
    "text": "All you need is love. But a little chocolate now and then doesn't hurt.",
    "original_text": null,
    "author": "Charles M. Schulz",
    "era": "Peanuts"
  },
  {
    "id": "mark-twain-1",
    "category": "Food Wit",
    "theme": "Let Food Fight It Out",
    "text": "Part of the secret of success in life is to eat what you like and let the food fight it out inside.",
    "original_text": null,
    "author": "Mark Twain",
    "era": "American Wit"
  },
  {
    "id": "oscar-wilde-1",
    "category": "Food Wit",
    "theme": "Good Dinners",
    "text": "After a good dinner one can forgive anybody, even one's own relations.",
    "original_text": null,
    "author": "Oscar Wilde",
    "era": "Playwright & Wit"
  },
  {
    "id": "wc-fields-1",
    "category": "Food Wit",
    "theme": "Cooking with Wine",
    "text": "I cook with wine, sometimes I even add it to the food.",
    "original_text": null,
    "author": "W.C. Fields",
    "era": "Classic Cinema"
  },
  {
    "id": "dolly-parton-1",
    "category": "Food Wit",
    "theme": "Life Priorities",
    "text": "My weaknesses have always been food and men — in that order.",
    "original_text": null,
    "author": "Dolly Parton",
    "era": "Music & Culture"
  },
  {
    "id": "ernestine-ulmer-1",
    "category": "Food Wit",
    "theme": "Dessert First",
    "text": "Life is uncertain. Eat dessert first.",
    "original_text": null,
    "author": "Ernestine Ulmer",
    "era": "American Author"
  },
  {
    "id": "irish-proverb-1",
    "category": "Food Wit",
    "theme": "Laughter at the Table",
    "text": "Laughter is brightest where food is best.",
    "original_text": null,
    "author": "Irish Proverb",
    "era": "Traditional"
  }
];
  var CSS_STYLES = ".daily-inspiration-overlay {\n  position: fixed;\n  inset: 0;\n  z-index: 10006;\n  background: rgba(15, 23, 42, 0.45);\n  backdrop-filter: blur(2.5px);\n  -webkit-backdrop-filter: blur(2.5px);\n  display: none;\n  align-items: flex-end;\n  justify-content: center;\n  opacity: 0;\n  transition: opacity 0.24s ease-out;\n}\n.daily-inspiration-overlay.show {\n  opacity: 1;\n}\n.daily-inspiration-drawer {\n  width: 100%;\n  max-width: 480px;\n  background: #ffffff;\n  border-radius: 24px 24px 0 0;\n  padding: 16px 20px max(24px, env(safe-area-inset-bottom)) 20px;\n  box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.22);\n  transform: translateY(100%);\n  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);\n  box-sizing: border-box;\n}\n.daily-inspiration-overlay.show .daily-inspiration-drawer {\n  transform: translateY(0);\n}\n.inspiration-handle {\n  width: 40px;\n  height: 4px;\n  background: #cbd5e1;\n  border-radius: 2px;\n  margin: 0 auto 12px auto;\n}\n.inspiration-header {\n  display: flex;\n  justify-content: space-between;\n  align-items: center;\n  margin-bottom: 6px;\n}\n.inspiration-header-left {\n  display: flex;\n  align-items: center;\n  gap: 8px;\n  flex-wrap: wrap;\n}\n.inspiration-sparkle {\n  font-size: 18px;\n  line-height: 1;\n}\n.inspiration-title {\n  font-size: 17px;\n  font-weight: 700;\n  color: #1e293b;\n  letter-spacing: -0.2px;\n}\n.inspiration-badge {\n  font-size: 11px;\n  font-weight: 700;\n  background: #ecfdf5;\n  color: #047857;\n  padding: 2px 8px;\n  border-radius: 12px;\n  border: 1px solid #a7f3d0;\n  letter-spacing: 0.2px;\n}\n.inspiration-close-btn {\n  background: #f1f5f9;\n  border: none;\n  font-size: 15px;\n  color: #64748b;\n  cursor: pointer;\n  width: 30px;\n  height: 30px;\n  border-radius: 50%;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  transition: background 0.15s ease, color 0.15s ease;\n}\n.inspiration-close-btn:hover {\n  background: #e2e8f0;\n  color: #1e293b;\n}\n.inspiration-greeting-line {\n  font-size: 13px;\n  font-weight: 600;\n  color: #059669;\n  margin-bottom: 12px;\n  display: flex;\n  align-items: center;\n  gap: 4px;\n}\n.inspiration-tester-bar {\n  background: #f8fafc;\n  border: 1px solid #e2e8f0;\n  border-radius: 10px;\n  padding: 8px 10px;\n  margin-bottom: 12px;\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 8px;\n}\n.tester-nav-btn {\n  background: #ffffff;\n  border: 1px solid #cbd5e1;\n  border-radius: 6px;\n  padding: 6px 10px;\n  font-size: 12px;\n  font-weight: 600;\n  color: #334155;\n  cursor: pointer;\n  white-space: nowrap;\n  transition: all 0.15s;\n}\n.tester-nav-btn:hover {\n  background: #f1f5f9;\n  border-color: #94a3b8;\n}\n.tester-counter-wrap {\n  flex: 1;\n  min-width: 0;\n}\n.tester-quote-select {\n  width: 100%;\n  font-size: 12px;\n  padding: 5px 6px;\n  border-radius: 6px;\n  border: 1px solid #cbd5e1;\n  background: #ffffff;\n  color: #1e293b;\n  font-weight: 500;\n  outline: none;\n}\n.inspiration-content-card {\n  background: linear-gradient(135deg, #fbfdf9 0%, #f4f9f4 100%);\n  border: 1.5px solid #d1fae5;\n  border-radius: 16px;\n  padding: 16px 16px 14px 16px;\n  margin-bottom: 16px;\n  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.05);\n}\n.inspiration-quote-text {\n  font-size: 15.5px;\n  font-style: italic;\n  line-height: 1.55;\n  color: #0f172a;\n  font-weight: 500;\n}\n.inspiration-original-wrap {\n  background: rgba(16, 185, 129, 0.08);\n  border-left: 3px solid #059669;\n  border-radius: 0 8px 8px 0;\n  padding: 8px 12px;\n  margin-top: 10px;\n}\n.inspiration-original-text {\n  font-size: 14px;\n  line-height: 1.6;\n  color: #065f46;\n  font-weight: 600;\n  font-family: system-ui, -apple-system, sans-serif;\n}\n.inspiration-footer-meta {\n  display: flex;\n  flex-wrap: wrap;\n  justify-content: space-between;\n  align-items: center;\n  margin-top: 12px;\n  padding-top: 10px;\n  border-top: 1px dashed #cbd5e1;\n  gap: 4px;\n}\n.inspiration-author-text {\n  font-size: 13px;\n  font-weight: 700;\n  color: #334155;\n}\n.inspiration-era-text {\n  font-size: 12px;\n  font-weight: 500;\n  color: #64748b;\n}\n.inspiration-actions {\n  display: flex;\n  gap: 10px;\n}\n.inspiration-btn-gotit {\n  width: 100%;\n  background: linear-gradient(135deg, #059669, #10b981);\n  color: #ffffff;\n  border: none;\n  padding: 13px;\n  border-radius: 12px;\n  font-size: 15px;\n  font-weight: 700;\n  cursor: pointer;\n  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.25);\n  transition: opacity 0.15s;\n}\n.inspiration-btn-gotit:hover {\n  opacity: 0.95;\n}";

  var currentQuoteIndex = 0;
  var isTesterMode = false;

  // ── Inject Styles ─────────────────────────────────────────────
  function injectStyles() {
    if (typeof document === 'undefined') return;
    if (document.getElementById('dailyInspirationStyles')) return;
    var style = document.createElement('style');
    style.id = 'dailyInspirationStyles';
    style.textContent = CSS_STYLES;
    document.head.appendChild(style);
  }

  // ── Timezone and Date-Aware Helpers ───────────────────────────
  // Uses a coprime dispersion generator step = 23 (gcd(23, 57) = 1) seeded by calendar date.
  // Guarantees:
  // 1. Dynamic category & author variety every single day (jumps between Thirukkural, chefs, philosophy, French, Italian, and wit).
  // 2. 100% unique quotes in any 57-day rolling window with zero duplicate repeats.
  // 3. Deterministic across devices and page reloads on the same calendar day.
  function getDailyQuoteIndex(date) {
    var d = date || new Date();
    var epoch = new Date(2026, 0, 1).getTime();
    var target = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    var dayIndex = Math.floor((target - epoch) / (1000 * 60 * 60 * 24));
    var totalCount = CULINARY_QUOTES.length;
    var step = 23; // Coprime to 57 (57 = 3 * 19)
    var offset = 11;
    return Math.abs((dayIndex * step + offset) % totalCount);
  }

  function getTimeOfDayGreeting(userName) {
    var now = new Date();
    var hour = now.getHours();
    var day = now.getDay();
    var isWeekend = (day === 0 || day === 6);
    var nameSuffix = userName ? (', ' + userName) : '';

    if (isWeekend && hour >= 8 && hour < 18) {
      return 'Happy Weekend' + nameSuffix + ' 🌿';
    }
    if (hour >= 5 && hour < 12) {
      return 'Good morning' + nameSuffix + ' ☕';
    }
    if (hour >= 12 && hour < 17) {
      return 'Good afternoon' + nameSuffix + ' ☀️';
    }
    if (hour >= 17 && hour < 22) {
      return 'Good evening' + nameSuffix + ' 🌙';
    }
    return 'Rest easy' + nameSuffix + ' ✨';
  }

  function getUserDisplayName() {
    try {
      if (window.currentCfg) {
        return window.currentCfg.display_name || (window.currentCfg.user_info && window.currentCfg.user_info.display_name) || '';
      }
      var cached = localStorage.getItem('listmate_cfg');
      if (cached) {
        var parsed = JSON.parse(cached);
        return parsed.display_name || '';
      }
    } catch (e) {}
    return '';
  }

  function checkIsTesterOrAdmin() {
    try {
      if (window.currentCfg) {
        var uid = (window.currentCfg.user_info && window.currentCfg.user_info.id) || window.currentCfg.user_id || (window.currentCfg.user === 'admin' ? 1 : null);
        var email = ((window.currentCfg.user_info && window.currentCfg.user_info.email) || window.currentCfg.email || '').trim().toLowerCase();
        var isAdmin = Boolean(window.currentCfg.is_admin || (window.currentCfg.user_info && window.currentCfg.user_info.is_admin));
        if (uid === 1 || email === 'venragh@gmail.com' || isAdmin) {
          return true;
        }
      }
      if (localStorage.getItem('listmate_tester_mode') === 'true' || localStorage.getItem('listmate_user_id') === '1') {
        return true;
      }
    } catch (e) {}
    return false;
  }

  // ── Render Drawer UI ─────────────────────────────────────────
  function ensureDrawerElement() {
    injectStyles();
    var overlay = document.getElementById('dailyInspirationOverlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'dailyInspirationOverlay';
    overlay.className = 'daily-inspiration-overlay';
    overlay.onclick = function(e) { handleBackdropClick(e); };

    overlay.innerHTML = [
      '<div id="dailyInspirationDrawer" class="daily-inspiration-drawer" onclick="event.stopPropagation()">',
      '  <div class="inspiration-handle"></div>',
      '  <div class="inspiration-header">',
      '    <div class="inspiration-header-left">',
      '      <span class="inspiration-sparkle">✨</span>',
      '      <span class="inspiration-title">Daily Inspiration</span>',
      '      <span id="inspirationCategoryBadge" class="inspiration-badge"></span>',
      '    </div>',
      '    <button class="inspiration-close-btn" onclick="window.dailyInspirationEngine.closeDrawer()" aria-label="Close">✕</button>',
      '  </div>',
      '  <div id="inspirationGreeting" class="inspiration-greeting-line"></div>',
      '  <!-- User ID #1 Tester Navigation Bar -->',
      '  <div id="inspirationTesterControls" class="inspiration-tester-bar" style="display:none;">',
      '    <button class="tester-nav-btn" onclick="window.dailyInspirationEngine.navigateQuote(-1)" title="Previous Proverb">◀ Prev</button>',
      '    <div class="tester-counter-wrap">',
      '      <select id="inspirationJumpSelect" class="tester-quote-select" onchange="window.dailyInspirationEngine.jumpToQuote(this.value)"></select>',
      '    </div>',
      '    <button class="tester-nav-btn" onclick="window.dailyInspirationEngine.navigateQuote(1)" title="Next Proverb">Next ▶</button>',
      '  </div>',
      '  <!-- Main Quote Card -->',
      '  <div class="inspiration-content-card">',
      '    <div id="inspirationMainQuote" class="inspiration-quote-text"></div>',
      '    <div id="inspirationOriginalWrap" class="inspiration-original-wrap" style="display:none;">',
      '      <div id="inspirationOriginalText" class="inspiration-original-text"></div>',
      '    </div>',
      '    <div class="inspiration-footer-meta">',
      '      <div id="inspirationAuthor" class="inspiration-author-text"></div>',
      '      <div id="inspirationEra" class="inspiration-era-text"></div>',
      '    </div>',
      '  </div>',
      '  <!-- Actions -->',
      '  <div class="inspiration-actions">',
      '    <button class="inspiration-btn-gotit" onclick="window.dailyInspirationEngine.closeDrawer()">Got it</button>',
      '  </div>',
      '</div>'
    ].join('');

    
    // Touch swipe-down to dismiss on mobile
    var startY = 0, currentY = 0, isDragging = false;
    var drawerEl = overlay.querySelector('.daily-inspiration-drawer');
    if (drawerEl) {
      drawerEl.addEventListener('touchstart', function(e) {
        startY = e.touches[0].clientY;
        isDragging = true;
      }, { passive: true });

      drawerEl.addEventListener('touchmove', function(e) {
        if (!isDragging) return;
        currentY = e.touches[0].clientY;
        var diff = currentY - startY;
        if (diff > 0) {
          drawerEl.style.transform = 'translateY(' + diff + 'px)';
        }
      }, { passive: true });

      drawerEl.addEventListener('touchend', function() {
        if (!isDragging) return;
        isDragging = false;
        var diff = currentY - startY;
        if (diff > 80) {
          closeDrawer();
        } else {
          drawerEl.style.transform = 'translateY(0)';
        }
      }, { passive: true });
    }

    document.body.appendChild(overlay);
    return overlay;
  }

  function renderQuote(index) {
    if (index < 0) index = CULINARY_QUOTES.length - 1;
    if (index >= CULINARY_QUOTES.length) index = 0;
    currentQuoteIndex = index;

    var q = CULINARY_QUOTES[currentQuoteIndex];
    if (!q) return;

    var greetingEl = document.getElementById('inspirationGreeting');
    if (greetingEl) {
      var userName = getUserDisplayName();
      greetingEl.textContent = getTimeOfDayGreeting(userName);
    }

    var badge = document.getElementById('inspirationCategoryBadge');
    if (badge) badge.textContent = q.category || 'Culinary Wisdom';

    var quoteEl = document.getElementById('inspirationMainQuote');
    if (quoteEl) quoteEl.textContent = '“' + q.text + '”';

    var origWrap = document.getElementById('inspirationOriginalWrap');
    var origText = document.getElementById('inspirationOriginalText');
    if (q.original_text && origWrap && origText) {
      origText.textContent = q.original_text;
      origWrap.style.display = 'block';
    } else if (origWrap) {
      origWrap.style.display = 'none';
    }

    var authorEl = document.getElementById('inspirationAuthor');
    if (authorEl) authorEl.textContent = '— ' + (q.author || 'Timeless Wisdom');

    var eraEl = document.getElementById('inspirationEra');
    if (eraEl) eraEl.textContent = q.era ? ('(' + q.era + ')') : '';

    // Tester controls update
    isTesterMode = checkIsTesterOrAdmin();
    var testerBar = document.getElementById('inspirationTesterControls');
    var jumpSelect = document.getElementById('inspirationJumpSelect');

    if (testerBar) {
      testerBar.style.display = isTesterMode ? 'flex' : 'none';
    }

    if (isTesterMode && jumpSelect) {
      if (jumpSelect.children.length !== CULINARY_QUOTES.length) {
        jumpSelect.innerHTML = '';
        CULINARY_QUOTES.forEach(function(item, idx) {
          var opt = document.createElement('option');
          opt.value = idx;
          opt.textContent = '[' + (idx + 1) + '/' + CULINARY_QUOTES.length + '] ' + item.author + ' (' + item.category + ')';
          jumpSelect.appendChild(opt);
        });
      }
      jumpSelect.value = currentQuoteIndex;
    }
  }

  function getLocalDateString() {
    var d = new Date();
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function recordSeen(dateStr) {
    try {
      var d = dateStr || getLocalDateString();
      if (window.currentCfg && window.currentCfg.user_info) {
        window.currentCfg.user_info.last_inspiration_seen_date = d;
      }
      if (typeof fetch === 'function') {
        fetch('/api/user/inspiration', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ seen_date: d }),
          credentials: 'include'
        }).catch(function() {});
      }
    } catch(e) {}
  }

  function openDrawer(forceManual, specificIndex) {
    ensureDrawerElement();
    var overlay = document.getElementById('dailyInspirationOverlay');
    if (!overlay) return;

    isTesterMode = checkIsTesterOrAdmin();

    if (typeof specificIndex === 'number' && specificIndex >= 0 && specificIndex < CULINARY_QUOTES.length) {
      currentQuoteIndex = specificIndex;
    } else {
      currentQuoteIndex = getDailyQuoteIndex();
    }

    renderQuote(currentQuoteIndex);

    overlay.style.display = 'flex';
    requestAnimationFrame(function() {
      overlay.classList.add('show');
    });

    recordSeen();
  }

  function closeDrawer() {
    var overlay = document.getElementById('dailyInspirationOverlay');
    if (!overlay) return;

    overlay.classList.remove('show');
    setTimeout(function() {
      overlay.style.display = 'none';
    }, 240);

    recordSeen();
  }

  function handleBackdropClick(e) {
    if (e.target && e.target.id === 'dailyInspirationOverlay') {
      closeDrawer();
    }
  }

  function navigateQuote(delta) {
    renderQuote(currentQuoteIndex + delta);
  }

  function jumpToQuote(val) {
    var idx = parseInt(val, 10);
    if (!isNaN(idx)) {
      renderQuote(idx);
    }
  }

  var hasTriggeredCadence = false;

  function evaluateAndTrigger(userInfo, forceDelay) {
    try {
      if (hasTriggeredCadence) return;
      if (!userInfo) return;

      // If disabled by user setting in DB, do not show automatically
      if (userInfo.daily_inspiration_enabled === false) return;

      var today = getLocalDateString();
      var lastSeen = userInfo.last_inspiration_seen_date;

      // If already marked seen for today in DB, do not show automatically
      if (lastSeen === today) {
        return;
      }

      // If NULL, empty, or prior date -> pop open automatically
      hasTriggeredCadence = true;
      userInfo.last_inspiration_seen_date = today;

      var delay = typeof forceDelay === 'number' ? forceDelay : 850;
      setTimeout(function() {
        // Defer if celebratory feedback modal or cleanup modal is currently visible
        var activeModal = document.querySelector('#feedbackModal.active, #cleanupModal.show, #actionConfirmModal.show');
        if (activeModal) {
          setTimeout(function() {
            var stillActive = document.querySelector('#feedbackModal.active, #cleanupModal.show, #actionConfirmModal.show');
            if (!stillActive) {
              openDrawer(false);
            }
          }, 2500);
          return;
        }
        openDrawer(false);
      }, delay);
    } catch(e) {}
  }

  function initCadence(forceDelay, serverUserInfo) {
    try {
      if (hasTriggeredCadence) return;
      if (typeof window !== 'undefined' && window.location) {
        var path = window.location.pathname || '';
        if (path !== '/' && path !== '' && path !== '/index.html') {
          return;
        }
      }

      var uInfo = serverUserInfo || (window.currentCfg && window.currentCfg.user_info);
      if (uInfo) {
        evaluateAndTrigger(uInfo, forceDelay);
        return;
      }

      // If serverUserInfo is not yet loaded in memory, fetch directly from database API
      if (typeof fetch === 'function') {
        fetch('/api/user/inspiration', { credentials: 'include' })
          .then(function(res) {
            if (!res.ok) return null;
            return res.json();
          })
          .then(function(data) {
            if (!data) return;
            evaluateAndTrigger(data, forceDelay);
          })
          .catch(function() {});
      }
    } catch(e) {}
  }

  // Public API
  window.dailyInspirationEngine = {
    quotes: CULINARY_QUOTES,
    getTimeOfDayGreeting: getTimeOfDayGreeting,
    getDailyQuoteIndex: getDailyQuoteIndex,
    openDrawer: openDrawer,
    closeDrawer: closeDrawer,
    handleBackdropClick: handleBackdropClick,
    navigateQuote: navigateQuote,
    jumpToQuote: jumpToQuote,
    initCadence: initCadence,
    checkIsTesterOrAdmin: checkIsTesterOrAdmin,
    recordSeen: recordSeen
  };

  // Auto-lifecycle bootstrap
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
          initCadence(900);
        }, 300);
      });
    } else {
      setTimeout(function() {
        initCadence(900);
      }, 300);
    }

    // Keyboard shortcut (Escape to close)
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        var overlay = document.getElementById('dailyInspirationOverlay');
        if (overlay && overlay.classList.contains('show')) {
          closeDrawer();
        }
      }
    });
  }

})(typeof window !== 'undefined' ? window : this);
