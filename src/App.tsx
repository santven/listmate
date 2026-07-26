import React, { useState, useEffect } from "react";
import { 
  ShoppingBag, 
  ShoppingCart, 
  Plus, 
  Trash2, 
  Check, 
  Sparkles, 
  ChefHat, 
  DollarSign, 
  AlertCircle, 
  ChevronDown, 
  ChevronUp, 
  Info, 
  Search, 
  Cpu, 
  Edit2, 
  X,
  TrendingDown,
  Sliders,
  GitBranch,
  CheckCircle2,
  Calendar,
  ListFilter,
  ArrowRight,
  HelpCircle,
  Maximize2
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { GroceryItem, MealPlanIngredientsResponse } from "./types";

// Standard categories definitions with styles
const CATEGORY_MAP: Record<string, { label: string; icon: any; color: string; bg: string; border: string }> = {
  "Produce": { label: "Produce", icon: "🥦", color: "text-emerald-700", bg: "bg-emerald-50/70", border: "border-emerald-100" },
  "Dairy & Eggs": { label: "Dairy & Eggs", icon: "🥛", color: "text-amber-700", bg: "bg-amber-50/70", border: "border-amber-100" },
  "Bakery": { label: "Bakery", icon: "🍞", color: "text-orange-700", bg: "bg-orange-50/70", border: "border-orange-100" },
  "Meat & Seafood": { label: "Meat & Seafood", icon: "🥩", color: "text-rose-700", bg: "bg-rose-50/70", border: "border-rose-100" },
  "Pantry": { label: "Pantry", icon: "🥫", color: "text-yellow-700", bg: "bg-yellow-50/70", border: "border-yellow-100" },
  "Frozen": { label: "Frozen", icon: "❄️", color: "text-blue-700", bg: "bg-blue-50/70", border: "border-blue-100" },
  "Beverages": { label: "Beverages", icon: "🧃", color: "text-purple-700", bg: "bg-purple-50/70", border: "border-purple-100" },
  "Snacks": { label: "Snacks", icon: "🍿", color: "text-pink-700", bg: "bg-pink-50/70", border: "border-pink-100" },
  "Household": { label: "Household", icon: "🧼", color: "text-indigo-700", bg: "bg-indigo-50/70", border: "border-indigo-100" },
  "Other": { label: "Other", icon: "🛍️", color: "text-stone-700", bg: "bg-stone-50/70", border: "border-stone-100" }
};

// Initial state helper with high quality initial mock items to show off instantly
const INITIAL_ITEMS: GroceryItem[] = [
  { id: "1", name: "Organic Avocados", category: "Produce", quantity: 3, unit: "bag", isPurchased: false, priceEstimated: 5.99, notes: "Look for medium softness", addedAt: new Date(Date.now() - 3600000).toISOString() },
  { id: "2", name: "Sourdough Bread", category: "Bakery", quantity: 1, unit: "loaf", isPurchased: true, priceEstimated: 4.49, notes: "Pre-sliced is best", addedAt: new Date(Date.now() - 7200000).toISOString() },
  { id: "3", name: "Free Range Eggs (Large)", category: "Dairy & Eggs", quantity: 1, unit: "carton", isPurchased: false, priceEstimated: 3.99, notes: "Check for cracks", addedAt: new Date(Date.now() - 10800000).toISOString() },
  { id: "4", name: "Fresh Atlantic Salmon", category: "Meat & Seafood", quantity: 1.5, unit: "lbs", isPurchased: false, priceEstimated: 18.99, notes: "Wild caught if available", addedAt: new Date(Date.now() - 14400000).toISOString() },
  { id: "5", name: "Paper Towels", category: "Household", quantity: 1, unit: "pack", isPurchased: true, priceEstimated: 7.29, notes: "6-roll giant pack", addedAt: new Date(Date.now() - 18000000).toISOString() }
];

export default function App() {
  // Grocery list core state
  const [items, setItems] = useState<GroceryItem[]>(() => {
    const saved = localStorage.getItem("listmate_grocery_items");
    return saved ? JSON.parse(saved) : INITIAL_ITEMS;
  });

  const [budget, setBudget] = useState<number>(() => {
    const saved = localStorage.getItem("listmate_grocery_budget");
    return saved ? parseFloat(saved) : 100.00;
  });

  // UI interaction states
  const [newItemName, setNewItemName] = useState("");
  const [newItemNotes, setNewItemNotes] = useState("");
  const [isCategorizing, setIsCategorizing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"category" | "name" | "price" | "date">("category");
  const [showPurchased, setShowPurchased] = useState(true);

  // Detail & Editing Panel Side-over State
  const [editingItem, setEditingItem] = useState<GroceryItem | null>(null);

  // Meal Planner State
  const [mealPlanDish, setMealPlanDish] = useState("");
  const [mealPlanServings, setMealPlanServings] = useState(4);
  const [isGeneratingMeal, setIsGeneratingMeal] = useState(false);
  const [generatedMealResponse, setGeneratedMealResponse] = useState<MealPlanIngredientsResponse | null>(null);
  const [mealPlanError, setMealPlanError] = useState<string | null>(null);

  // Developer Integration Logs State
  const [aiLogs, setAiLogs] = useState<{ timestamp: string; type: string; request: string; response: any }[]>([]);
  const [showDevLogs, setShowDevLogs] = useState(false);
  const [gitStatus, setGitStatus] = useState<"clean" | "changes" | "syncing" | "synced">("clean");

  // Persist state
  useEffect(() => {
    localStorage.setItem("listmate_grocery_items", JSON.stringify(items));
  }, [items]);

  useEffect(() => {
    localStorage.setItem("listmate_grocery_budget", budget.toString());
  }, [budget]);

  // Log helper
  const addLog = (type: string, request: string, response: any) => {
    setAiLogs(prev => [
      {
        timestamp: new Date().toLocaleTimeString(),
        type,
        request,
        response
      },
      ...prev
    ]);
  };

  // Quick Add Item with automatic AI categorization
  const handleAddItem = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!newItemName.trim()) return;

    const tempId = Math.random().toString(36).substring(2, 9);
    const addedAt = new Date().toISOString();
    const itemName = newItemName.trim();
    const itemNotes = newItemNotes.trim();

    // Create a temporary placeholder item with 'Other' category
    const placeholderItem: GroceryItem = {
      id: tempId,
      name: itemName,
      category: "Other",
      quantity: 1,
      unit: "pcs",
      isPurchased: false,
      priceEstimated: 1.99,
      notes: itemNotes || "Analyzing with AI...",
      addedAt
    };

    setItems(prev => [placeholderItem, ...prev]);
    setNewItemName("");
    setNewItemNotes("");
    setIsCategorizing(true);
    setGitStatus("changes");

    try {
      const response = await fetch("/api/grocery/categorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: itemName, notes: itemNotes })
      });

      if (!response.ok) throw new Error("Server categorization failed");
      const data = await response.json();

      // Log the action for the developer console
      addLog("Item Categorization", `POST /api/grocery/categorize { name: "${itemName}", notes: "${itemNotes}" }`, data);

      // Validate category response
      const matchedCategory = CATEGORY_MAP[data.category] ? data.category : "Other";

      setItems(prev => prev.map(item => {
        if (item.id === tempId) {
          return {
            ...item,
            category: matchedCategory,
            quantity: data.quantity || 1,
            unit: data.unit || "pcs",
            priceEstimated: data.priceEstimated || 2.49,
            notes: data.notes || itemNotes || ""
          };
        }
        return item;
      }));
    } catch (err) {
      console.error("AI Categorization Error:", err);
      // Keep placeholder item but remove "Analyzing..." message
      setItems(prev => prev.map(item => {
        if (item.id === tempId) {
          return { ...item, notes: itemNotes };
        }
        return item;
      }));
    } finally {
      setIsCategorizing(false);
    }
  };

  // Toggle item purchased status
  const handleTogglePurchased = (id: string) => {
    setItems(prev => prev.map(item => {
      if (item.id === id) {
        return { ...item, isPurchased: !item.isPurchased };
      }
      return item;
    }));
    setGitStatus("changes");
  };

  // Delete item from list
  const handleDeleteItem = (id: string) => {
    setItems(prev => prev.filter(item => item.id !== id));
    setGitStatus("changes");
    if (editingItem?.id === id) {
      setEditingItem(null);
    }
  };

  // Save changes to edited item
  const handleSaveEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingItem) return;

    setItems(prev => prev.map(item => {
      if (item.id === editingItem.id) {
        return editingItem;
      }
      return item;
    }));
    setEditingItem(null);
    setGitStatus("changes");
  };

  // AI Meal planner ingredient generator
  const handleGenerateMealPlan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mealPlanDish.trim()) return;

    setIsGeneratingMeal(true);
    setMealPlanError(null);
    setGeneratedMealResponse(null);

    try {
      const response = await fetch("/api/grocery/generate-from-meal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dish: mealPlanDish.trim(), servings: mealPlanServings })
      });

      if (!response.ok) throw new Error("Failed to generate ingredients");
      const data = await response.json();

      addLog("Meal Planner Ingredients", `POST /api/grocery/generate-from-meal { dish: "${mealPlanDish}", servings: ${mealPlanServings} }`, data);
      setGeneratedMealResponse(data);
    } catch (err: any) {
      console.error("Meal Generation error:", err);
      setMealPlanError(err.message || "An error occurred while calling the Gemini API.");
    } finally {
      setIsGeneratingMeal(false);
    }
  };

  // Add all generated meal ingredients to the grocery list
  const handleAddMealIngredientsToList = () => {
    if (!generatedMealResponse || !generatedMealResponse.ingredients) return;

    const newItems: GroceryItem[] = generatedMealResponse.ingredients.map((ing, i) => ({
      id: `meal-${Date.now()}-${i}`,
      name: ing.name,
      category: CATEGORY_MAP[ing.category] ? ing.category : "Other",
      quantity: ing.quantity,
      unit: ing.unit,
      isPurchased: false,
      priceEstimated: ing.priceEstimated,
      notes: ing.notes || `${generatedMealResponse.dish} ingredient`,
      addedAt: new Date().toISOString()
    }));

    setItems(prev => [...newItems, ...prev]);
    setGeneratedMealResponse(null);
    setMealPlanDish("");
    setGitStatus("changes");
  };

  // Commit / Sync code simulation for issue #112 sandbox context
  const handleCommitSync = () => {
    setGitStatus("syncing");
    setTimeout(() => {
      setGitStatus("synced");
      setTimeout(() => {
        setGitStatus("clean");
      }, 3000);
    }, 2000);
  };

  // Clear list completely
  const handleClearAll = () => {
    if (window.confirm("Are you sure you want to clear your entire grocery list?")) {
      setItems([]);
      setGitStatus("changes");
    }
  };

  // Statistics & Financial Calculations
  const totalItemsCount = items.length;
  const purchasedItemsCount = items.filter(i => i.isPurchased).length;
  const activeItemsCount = totalItemsCount - purchasedItemsCount;

  const estimatedTotalCost = items.reduce((sum, item) => sum + (item.priceEstimated * item.quantity), 0);
  const purchasedCost = items.filter(i => i.isPurchased).reduce((sum, item) => sum + (item.priceEstimated * item.quantity), 0);
  const activeCost = estimatedTotalCost - purchasedCost;

  const budgetProgressPercent = Math.min((estimatedTotalCost / budget) * 100, 100);
  const isOverBudget = estimatedTotalCost > budget;

  // Search, filter, and sort logic
  const filteredItems = items
    .filter(item => {
      // Search filter
      const matchesSearch = item.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            (item.notes && item.notes.toLowerCase().includes(searchQuery.toLowerCase()));
      // Category filter
      const matchesCategory = !filterCategory || item.category === filterCategory;
      // Purchased filter
      const matchesPurchased = showPurchased || !item.isPurchased;

      return matchesSearch && matchesCategory && matchesPurchased;
    })
    .sort((a, b) => {
      if (sortBy === "name") {
        return a.name.localeCompare(b.name);
      }
      if (sortBy === "price") {
        return (b.priceEstimated * b.quantity) - (a.priceEstimated * a.quantity);
      }
      if (sortBy === "date") {
        return new Date(b.addedAt).getTime() - new Date(a.addedAt).getTime();
      }
      // Group by category, then by purchase state, then name
      if (sortBy === "category") {
        const catCompare = a.category.localeCompare(b.category);
        if (catCompare !== 0) return catCompare;
        if (a.isPurchased !== b.isPurchased) return a.isPurchased ? 1 : -1;
        return a.name.localeCompare(b.name);
      }
      return 0;
    });

  // Unique categories actively present in the list
  const activeListCategories = Array.from(new Set(items.map(i => i.category)));

  return (
    <div className="min-h-screen bg-[#FDFBF7] text-stone-900 font-sans antialiased selection:bg-emerald-100 selection:text-emerald-950 flex flex-col">
      
      {/* Sandbox Development Header for Issue #112 */}
      <header className="bg-stone-900 text-stone-100 border-b border-stone-800 py-3 px-4 sm:px-6 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div className="flex items-center gap-3">
          <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 p-1.5 rounded-lg flex items-center justify-center">
            <GitBranch size={16} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-stone-400">feat/112-grocery-list-app</span>
              <span className="bg-emerald-900/40 text-emerald-300 border border-emerald-800 text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded">
                Active Sandbox
              </span>
            </div>
            <h1 className="text-sm font-semibold tracking-tight text-stone-100">
              Issue #112: Full-Stack AI Grocery Engine Integration
            </h1>
          </div>
        </div>
        
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button
            onClick={() => setShowDevLogs(!showDevLogs)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              showDevLogs 
                ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300" 
                : "bg-stone-800 border-stone-700 hover:border-stone-600 text-stone-300"
            }`}
          >
            <Cpu size={14} />
            <span>AI Engine Logs</span>
            {aiLogs.length > 0 && (
              <span className="bg-emerald-500 text-stone-950 font-bold px-1.5 py-0.2 rounded-full text-[10px] ml-1">
                {aiLogs.length}
              </span>
            )}
          </button>

          <button
            onClick={handleCommitSync}
            disabled={gitStatus === "syncing" || gitStatus === "synced"}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all shadow-sm ${
              gitStatus === "changes" 
                ? "bg-amber-500 hover:bg-amber-400 text-stone-950 border-amber-600" 
                : gitStatus === "syncing"
                ? "bg-stone-800 border-stone-700 text-stone-400 cursor-not-allowed"
                : gitStatus === "synced"
                ? "bg-emerald-500 text-stone-950 border-emerald-600"
                : "bg-stone-800 border-stone-700 hover:border-stone-600 text-stone-300"
            }`}
          >
            {gitStatus === "syncing" ? (
              <>
                <div className="w-3 h-3 border-2 border-stone-400 border-t-transparent rounded-full animate-spin" />
                <span>Syncing...</span>
              </>
            ) : gitStatus === "synced" ? (
              <>
                <CheckCircle2 size={14} />
                <span>Synced to Issue #112</span>
              </>
            ) : (
              <>
                <Check size={14} />
                <span>{gitStatus === "changes" ? "Commit Changes" : "Sandbox Synced"}</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 py-6 md:py-8 grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Hand: Controls & Main List View (8 columns on large screen) */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          
          {/* Hero Premium Dashboard Overview Block */}
          <section className="bg-white border border-stone-200/80 rounded-xl p-5 md:p-6 shadow-[0_2px_8px_-3px_rgba(0,0,0,0.05)] grid grid-cols-1 md:grid-cols-12 gap-6 items-center">
            
            {/* Title & Brand */}
            <div className="md:col-span-4 flex items-center gap-3">
              <div className="w-12 h-12 bg-emerald-600 text-white rounded-xl flex items-center justify-center shadow-md shadow-emerald-600/10">
                <ShoppingCart size={22} strokeWidth={2.5} />
              </div>
              <div>
                <span className="text-[11px] font-bold tracking-widest text-emerald-700 uppercase">Premium Planner</span>
                <h2 className="text-2xl font-bold text-stone-900 tracking-tight leading-none mt-0.5">ListMate</h2>
              </div>
            </div>

            {/* Quick Metrics */}
            <div className="md:col-span-8 grid grid-cols-3 gap-4 border-t md:border-t-0 md:border-l border-stone-100 pt-4 md:pt-0 md:pl-6">
              
              <div className="flex flex-col">
                <span className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Total Items</span>
                <div className="flex items-baseline gap-1 mt-1">
                  <span className="text-2xl font-bold text-stone-900">{totalItemsCount}</span>
                  {activeItemsCount > 0 && (
                    <span className="text-xs font-medium text-stone-500">({activeItemsCount} left)</span>
                  )}
                </div>
              </div>

              <div className="flex flex-col">
                <span className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Est. Total Cost</span>
                <div className="flex items-baseline gap-0.5 mt-1 text-emerald-700">
                  <span className="text-xs font-semibold">$</span>
                  <span className="text-2xl font-bold leading-none">{estimatedTotalCost.toFixed(2)}</span>
                </div>
              </div>

              <div className="flex flex-col">
                <span className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Remaining Budget</span>
                <div className="flex items-baseline gap-0.5 mt-1">
                  <span className="text-xs font-semibold">$</span>
                  <span className={`text-2xl font-bold leading-none ${isOverBudget ? "text-rose-600" : "text-stone-900"}`}>
                    {(budget - estimatedTotalCost).toFixed(2)}
                  </span>
                </div>
              </div>

            </div>

            {/* Live Budget Tracker Bar */}
            <div className="md:col-span-12 mt-2 pt-4 border-t border-stone-100 flex flex-col gap-2">
              <div className="flex justify-between items-center text-xs">
                <span className="text-stone-500 font-medium">Budget: ${budget.toFixed(2)}</span>
                <div className="flex items-center gap-3">
                  <button 
                    onClick={() => {
                      const res = prompt("Enter custom budget limit ($):", budget.toString());
                      if (res && !isNaN(parseFloat(res))) setBudget(parseFloat(res));
                    }}
                    className="text-emerald-700 hover:text-emerald-800 font-bold transition-colors"
                  >
                    Adjust Limit
                  </button>
                  <span className={`font-semibold ${isOverBudget ? "text-rose-600" : "text-emerald-700"}`}>
                    {budgetProgressPercent.toFixed(0)}% Spent
                  </span>
                </div>
              </div>
              
              <div className="w-full h-2.5 bg-stone-100 rounded-full overflow-hidden flex">
                <div 
                  className={`h-full rounded-full transition-all duration-500 ${
                    isOverBudget ? "bg-rose-500" : "bg-emerald-600"
                  }`}
                  style={{ width: `${budgetProgressPercent}%` }}
                />
              </div>

              {isOverBudget && (
                <div className="mt-1 bg-rose-50 border border-rose-100 rounded-lg p-2.5 flex items-start gap-2.5">
                  <AlertCircle size={15} className="text-rose-600 shrink-0 mt-0.5" />
                  <p className="text-[11px] text-rose-800 leading-normal">
                    <span className="font-bold">Over Budget!</span> Try deleting some non-essential snacks, or tap an item to reduce the quantity.
                  </p>
                </div>
              )}
            </div>

          </section>

          {/* Quick Add Engine Block */}
          <section className="bg-white border border-stone-200/80 rounded-xl p-5 md:p-6 shadow-[0_2px_8px_-3px_rgba(0,0,0,0.05)]">
            <h3 className="text-xs font-bold uppercase tracking-wider text-stone-400 mb-3 flex items-center gap-1.5">
              <Sparkles size={13} className="text-emerald-600" />
              <span>AI Fast Add & Categorizer (Gemini 3.5 Flash Lite)</span>
            </h3>
            
            <form onSubmit={handleAddItem} className="space-y-3">
              <div className="flex flex-col md:flex-row gap-3">
                <div className="flex-1 relative">
                  <input
                    type="text"
                    value={newItemName}
                    onChange={(e) => setNewItemName(e.target.value)}
                    placeholder="Enter item (e.g. 2 cartons of organic skim milk, 4 yellow bananas...)"
                    className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2.5 pl-3.5 pr-10 text-sm placeholder:text-stone-400 outline-none transition-all text-stone-900 font-medium"
                  />
                  <div className="absolute right-3 top-3 text-stone-400">
                    <ShoppingBag size={16} />
                  </div>
                </div>

                <div className="w-full md:w-60">
                  <input
                    type="text"
                    value={newItemNotes}
                    onChange={(e) => setNewItemNotes(e.target.value)}
                    placeholder="Notes (optional, e.g., low-fat)"
                    className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2.5 px-3.5 text-sm placeholder:text-stone-400 outline-none transition-all text-stone-900 font-medium"
                  />
                </div>

                <button
                  type="submit"
                  disabled={!newItemName.trim() || isCategorizing}
                  className="bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-sm px-6 py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2 shadow-sm shadow-emerald-700/10"
                >
                  {isCategorizing ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Analyzing...</span>
                    </>
                  ) : (
                    <>
                      <Plus size={16} strokeWidth={2.5} />
                      <span>Add Item</span>
                    </>
                  )}
                </button>
              </div>

              <div className="flex justify-between items-center text-[11px] text-stone-400 font-medium pt-1 px-1">
                <span>💡 Type quantities & details—the Gemini engine handles the rest!</span>
                {isCategorizing && <span className="text-emerald-600 font-bold animate-pulse">Assigning category, estimating price...</span>}
              </div>
            </form>
          </section>

          {/* Grocery List Container */}
          <section className="bg-white border border-stone-200/80 rounded-xl shadow-[0_2px_8px_-3px_rgba(0,0,0,0.05)] overflow-hidden">
            
            {/* Filter & Toolbar Area */}
            <div className="border-b border-stone-100 p-4 bg-stone-50/50 flex flex-col md:flex-row gap-3 justify-between items-start md:items-center">
              
              {/* Search & Filter Categories */}
              <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
                <div className="relative w-full md:w-56">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search grocery item..."
                    className="w-full bg-white border border-stone-200 focus:border-emerald-600 rounded-lg py-1.5 pl-8 pr-3 text-xs placeholder:text-stone-400 outline-none transition-all"
                  />
                  <div className="absolute left-2.5 top-2.5 text-stone-400">
                    <Search size={13} />
                  </div>
                  {searchQuery && (
                    <button 
                      onClick={() => setSearchQuery("")} 
                      className="absolute right-2.5 top-2 text-stone-400 hover:text-stone-600"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>

                {/* Category Quick Filter Badge selector */}
                <div className="relative">
                  <select
                    value={filterCategory || ""}
                    onChange={(e) => setFilterCategory(e.target.value || null)}
                    className="bg-white border border-stone-200 text-stone-600 rounded-lg py-1.5 px-3.5 pr-8 text-xs font-semibold outline-none transition-all appearance-none cursor-pointer hover:border-stone-300"
                  >
                    <option value="">All Categories</option>
                    {Object.keys(CATEGORY_MAP).map(catName => (
                      <option key={catName} value={catName}>{catName}</option>
                    ))}
                  </select>
                  <div className="absolute right-2.5 top-2.5 text-stone-400 pointer-events-none">
                    <ChevronDown size={12} />
                  </div>
                </div>
              </div>

              {/* Sort & Action controls */}
              <div className="flex items-center gap-3 w-full md:w-auto justify-between md:justify-end">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] font-bold text-stone-400 uppercase">Sort:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as any)}
                    className="bg-transparent text-xs font-bold text-stone-700 hover:text-emerald-700 outline-none cursor-pointer"
                  >
                    <option value="category">Category Group</option>
                    <option value="name">Alphabetical</option>
                    <option value="price">Highest Cost</option>
                    <option value="date">Date Added</option>
                  </select>
                </div>

                <div className="h-4 w-px bg-stone-200 hidden md:block" />

                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs text-stone-600 font-semibold cursor-pointer">
                    <input
                      type="checkbox"
                      checked={showPurchased}
                      onChange={(e) => setShowPurchased(e.target.checked)}
                      className="rounded border-stone-300 text-emerald-600 focus:ring-emerald-500 w-3.5 h-3.5 cursor-pointer"
                    />
                    <span>Show Purchased</span>
                  </label>

                  {items.length > 0 && (
                    <button
                      onClick={handleClearAll}
                      className="text-stone-400 hover:text-rose-600 font-bold text-xs flex items-center gap-1 transition-colors pl-2 border-l border-stone-200"
                    >
                      <Trash2 size={12} />
                      <span>Clear All</span>
                    </button>
                  )}
                </div>
              </div>

            </div>

            {/* List Body */}
            <div className="divide-y divide-stone-100 min-h-[300px]">
              {filteredItems.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                  <div className="w-16 h-16 bg-stone-50 rounded-full flex items-center justify-center border border-stone-100 mb-4 text-stone-300">
                    <ShoppingBag size={28} />
                  </div>
                  <h4 className="text-base font-bold text-stone-800">Your Listmate is empty</h4>
                  <p className="text-xs text-stone-500 max-w-sm mt-1 leading-normal">
                    {searchQuery || filterCategory 
                      ? "No items match your active search filter options. Clear filter/search to reset."
                      : "Type an item in the search field above or use the AI Meal Planner on the right to auto-populate your grocery list."}
                  </p>
                  {(searchQuery || filterCategory) && (
                    <button
                      onClick={() => {
                        setSearchQuery("");
                        setFilterCategory(null);
                      }}
                      className="mt-4 bg-stone-100 hover:bg-stone-200 text-stone-700 font-bold text-xs px-4 py-2 rounded-lg transition-colors"
                    >
                      Reset Active Filters
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex flex-col">
                  <AnimatePresence initial={false}>
                    {filteredItems.map((item, index) => {
                      const catStyle = CATEGORY_MAP[item.category] || CATEGORY_MAP["Other"];
                      const itemTotalCost = item.priceEstimated * item.quantity;
                      
                      // Render Category Header if grouping by Category
                      const showHeader = sortBy === "category" && 
                        (index === 0 || filteredItems[index - 1].category !== item.category);

                      return (
                        <div key={item.id} className="flex flex-col">
                          {showHeader && (
                            <div className="bg-[#FAF9F6] px-4 py-2 flex items-center justify-between border-t border-stone-100 first:border-t-0">
                              <div className="flex items-center gap-2">
                                <span className="text-base leading-none">{catStyle.icon}</span>
                                <span className="text-xs font-black uppercase tracking-wider text-stone-600">{catStyle.label}</span>
                              </div>
                              <span className="text-[10px] font-black text-stone-400">
                                {items.filter(i => i.category === item.category).length} items
                              </span>
                            </div>
                          )}

                          <motion.div 
                            layout
                            initial={{ opacity: 0, y: 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            transition={{ duration: 0.15 }}
                            className={`flex items-center justify-between px-4 py-3.5 hover:bg-stone-50/50 transition-all ${
                              item.isPurchased ? "bg-stone-50/30 text-stone-400" : ""
                            }`}
                          >
                            <div className="flex items-center gap-3 flex-1 min-w-0 mr-4">
                              {/* Checkbox */}
                              <button
                                onClick={() => handleTogglePurchased(item.id)}
                                className={`w-5 h-5 rounded-md flex items-center justify-center border transition-all shrink-0 ${
                                  item.isPurchased 
                                    ? "bg-emerald-600 border-emerald-600 text-white" 
                                    : "border-stone-300 hover:border-emerald-600 bg-white"
                                }`}
                              >
                                {item.isPurchased && <Check size={14} strokeWidth={3} />}
                              </button>

                              {/* Item Text & Subtitle */}
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span className={`text-sm font-bold truncate ${
                                    item.isPurchased ? "line-through text-stone-400" : "text-stone-900"
                                  }`}>
                                    {item.name}
                                  </span>
                                  
                                  {/* Small Category Badge (only if NOT sorted by Category) */}
                                  {sortBy !== "category" && (
                                    <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${catStyle.bg} ${catStyle.border} ${catStyle.color}`}>
                                      {item.category}
                                    </span>
                                  )}
                                </div>

                                {item.notes && (
                                  <p className={`text-xs mt-0.5 truncate ${
                                    item.isPurchased ? "text-stone-300" : "text-stone-500"
                                  }`}>
                                    {item.notes}
                                  </p>
                                )}
                              </div>
                            </div>

                            {/* Quantity & Unit, Cost, and Actions */}
                            <div className="flex items-center gap-4 shrink-0">
                              
                              {/* Quantity Counter */}
                              <div className="text-right flex flex-col items-end">
                                <span className="text-xs font-extrabold text-stone-800">
                                  {item.quantity} {item.unit}
                                </span>
                                <span className="text-[10px] text-stone-400 font-medium">
                                  ${item.priceEstimated.toFixed(2)} / {item.unit}
                                </span>
                              </div>

                              {/* Total Price Column */}
                              <div className="w-16 text-right font-black text-sm text-stone-900">
                                <span className={item.isPurchased ? "text-stone-400 font-medium" : ""}>
                                  ${itemTotalCost.toFixed(2)}
                                </span>
                              </div>

                              {/* Quick edit & delete buttons */}
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => setEditingItem(item)}
                                  className="p-1 text-stone-400 hover:text-stone-600 rounded-lg hover:bg-stone-100 transition-colors"
                                  title="Edit details"
                                >
                                  <Edit2 size={13} />
                                </button>
                                <button
                                  onClick={() => handleDeleteItem(item.id)}
                                  className="p-1 text-stone-400 hover:text-rose-600 rounded-lg hover:bg-stone-100 transition-colors"
                                  title="Remove item"
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>

                            </div>
                          </motion.div>
                        </div>
                      );
                    })}
                  </AnimatePresence>
                </div>
              )}
            </div>

            {/* List Footer Total Summarizer */}
            {items.length > 0 && (
              <div className="bg-stone-50 p-4 border-t border-stone-100 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div className="text-xs text-stone-500 font-medium">
                  Showing <span className="font-bold text-stone-700">{filteredItems.length}</span> of {items.length} items
                  {purchasedItemsCount > 0 && (
                    <span> ({purchasedItemsCount} purchased, {activeItemsCount} remaining)</span>
                  )}
                </div>

                <div className="flex items-center gap-6 self-end sm:self-auto text-right">
                  <div>
                    <span className="text-[10px] font-bold uppercase text-stone-400 tracking-wider block">Checked Off</span>
                    <span className="text-xs font-bold text-emerald-700">${purchasedCost.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] font-bold uppercase text-stone-400 tracking-wider block">Remaining Cost</span>
                    <span className="text-xs font-bold text-stone-600">${activeCost.toFixed(2)}</span>
                  </div>
                  <div className="border-l border-stone-200 pl-4">
                    <span className="text-[10px] font-bold uppercase text-stone-400 tracking-wider block">Total Estimated</span>
                    <span className="text-base font-black text-stone-900">${estimatedTotalCost.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            )}

          </section>

        </div>

        {/* Right Hand Side: AI Tools & Dev Logs (4 columns on large screen) */}
        <div className="lg:col-span-4 flex flex-col gap-6">
          
          {/* AI Recipe / Meal Planner Import Panel */}
          <section className="bg-white border border-stone-200/80 rounded-xl p-5 shadow-[0_2px_8px_-3px_rgba(0,0,0,0.05)]">
            <div className="flex items-center gap-2 mb-4">
              <div className="bg-emerald-100 text-emerald-800 p-2 rounded-lg">
                <ChefHat size={18} />
              </div>
              <div>
                <h3 className="text-base font-bold text-stone-900 tracking-tight leading-none">AI Recipe Builder</h3>
                <span className="text-[10px] text-stone-400 font-semibold tracking-wider uppercase">Meal Plan Generator</span>
              </div>
            </div>

            <p className="text-xs text-stone-500 mb-4 leading-relaxed">
              Enter any dish or meal idea, and Listmate will automatically formulate a full grocery list of ingredients and estimated prices!
            </p>

            <form onSubmit={handleGenerateMealPlan} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                  Dish / Recipe Description
                </label>
                <input
                  type="text"
                  value={mealPlanDish}
                  onChange={(e) => setMealPlanDish(e.target.value)}
                  placeholder="e.g. Classic Beef Lasagna, Keto Salmon Bowl, Tofu Stir Fry..."
                  className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3 text-xs placeholder:text-stone-400 outline-none transition-all font-medium"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                    Servings
                  </label>
                  <div className="relative">
                    <select
                      value={mealPlanServings}
                      onChange={(e) => setMealPlanServings(parseInt(e.target.value))}
                      className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3 pr-8 text-xs font-medium outline-none transition-all appearance-none cursor-pointer"
                    >
                      {[1, 2, 4, 6, 8, 10, 12].map(n => (
                        <option key={n} value={n}>{n} Servings</option>
                      ))}
                    </select>
                    <div className="absolute right-2.5 top-2.5 text-stone-400 pointer-events-none">
                      <ChevronDown size={12} />
                    </div>
                  </div>
                </div>

                <div className="flex items-end">
                  <button
                    type="submit"
                    disabled={isGeneratingMeal || !mealPlanDish.trim()}
                    className="w-full bg-stone-900 hover:bg-stone-800 disabled:bg-stone-300 text-white font-bold text-xs py-2 px-4 rounded-lg transition-colors flex items-center justify-center gap-1.5 shadow-sm h-[34px]"
                  >
                    {isGeneratingMeal ? (
                      <>
                        <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        <span>Planning...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles size={13} className="text-amber-400" />
                        <span>Generate List</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {mealPlanError && (
                <div className="bg-rose-50 border border-rose-100 rounded-lg p-3 text-xs text-rose-800 leading-normal flex gap-2">
                  <AlertCircle size={14} className="text-rose-600 shrink-0 mt-0.5" />
                  <span>{mealPlanError}</span>
                </div>
              )}
            </form>

            {/* Generated Recipe Ingredients Box */}
            {generatedMealResponse && (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-5 border border-stone-200 rounded-xl overflow-hidden bg-stone-50"
              >
                <div className="bg-stone-100 p-3 flex justify-between items-center border-b border-stone-200">
                  <div>
                    <h4 className="text-xs font-bold text-stone-800 truncate max-w-[200px]">{generatedMealResponse.dish}</h4>
                    <span className="text-[9px] text-stone-400 font-bold uppercase tracking-wider block">
                      {generatedMealResponse.ingredients.length} Ingredients • {generatedMealResponse.servings} Servings
                    </span>
                  </div>
                  <button 
                    onClick={() => setGeneratedMealResponse(null)}
                    className="text-stone-400 hover:text-stone-600"
                  >
                    <X size={14} />
                  </button>
                </div>

                <div className="max-h-[220px] overflow-y-auto divide-y divide-stone-100 p-1 bg-white">
                  {generatedMealResponse.ingredients.map((ing, i) => (
                    <div key={i} className="p-2 flex justify-between items-center text-xs">
                      <div className="min-w-0 mr-3">
                        <p className="font-bold text-stone-800 truncate">{ing.name}</p>
                        {ing.notes && <p className="text-[10px] text-stone-400 truncate">{ing.notes}</p>}
                      </div>
                      <div className="text-right shrink-0">
                        <span className="font-extrabold text-stone-900 bg-stone-100 px-1.5 py-0.5 rounded text-[10px]">
                          {ing.quantity} {ing.unit}
                        </span>
                        <p className="text-[10px] text-emerald-700 font-bold mt-0.5">${ing.priceEstimated.toFixed(2)}</p>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="p-3 border-t border-stone-200 bg-stone-50">
                  <button
                    onClick={handleAddMealIngredientsToList}
                    className="w-full bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs py-2 rounded-lg transition-colors flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <Plus size={13} strokeWidth={2.5} />
                    <span>Import All to My Grocery List</span>
                  </button>
                </div>
              </motion.div>
            )}

          </section>

          {/* AI Smart Tips Widget */}
          <section className="bg-gradient-to-br from-emerald-900 to-stone-900 text-emerald-100 rounded-xl p-5 shadow-[0_2px_8px_-3px_rgba(0,0,0,0.1)]">
            <h4 className="text-xs font-bold uppercase tracking-widest text-emerald-400 flex items-center gap-1.5 mb-2.5">
              <TrendingDown size={13} />
              <span>Smart Shopper Budget Guard</span>
            </h4>
            <p className="text-[11px] text-emerald-200/80 leading-relaxed mb-4">
              Here is how you can stretch your grocery budget. Swaps recommended based on standard grocery averages:
            </p>

            <div className="space-y-3">
              <div className="bg-white/5 border border-white/10 rounded-lg p-2.5">
                <span className="text-[9px] font-black uppercase text-amber-400 tracking-wider">Save up to $12.00</span>
                <p className="text-xs font-bold text-white mt-0.5">Replace Fresh Salmon</p>
                <p className="text-[11px] text-emerald-200/75 mt-0.5">Consider frozen cod fillets or wild-caught canned tuna. High in protein, half the cost!</p>
              </div>

              <div className="bg-white/5 border border-white/10 rounded-lg p-2.5">
                <span className="text-[9px] font-black uppercase text-emerald-400 tracking-wider">Bulk Buying Tip</span>
                <p className="text-xs font-bold text-white mt-0.5">Organic Avocados</p>
                <p className="text-[11px] text-emerald-200/75 mt-0.5">Purchasing loose avocados instead of bagged can save up to $1.20 per unit. Look for varying ripeness.</p>
              </div>
            </div>
          </section>

        </div>

      </main>

      {/* Slide-over Item Detail Editing Panel */}
      <AnimatePresence>
        {editingItem && (
          <>
            {/* Backdrop */}
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.4 }}
              exit={{ opacity: 0 }}
              onClick={() => setEditingItem(null)}
              className="fixed inset-0 bg-stone-950 z-40 cursor-pointer"
            />
            
            {/* Panel */}
            <motion.div 
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed right-0 top-0 bottom-0 w-full sm:w-[400px] bg-white border-l border-stone-200 shadow-2xl z-50 p-6 flex flex-col justify-between"
            >
              <div>
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <h3 className="text-lg font-extrabold text-stone-900 tracking-tight leading-none">Edit Grocery Item</h3>
                    <span className="text-[10px] text-stone-400 font-bold tracking-wider uppercase mt-1.5 block">Configure item details</span>
                  </div>
                  <button 
                    onClick={() => setEditingItem(null)}
                    className="p-1.5 text-stone-400 hover:text-stone-600 rounded-lg hover:bg-stone-50 transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>

                <form onSubmit={handleSaveEdit} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                      Item Name
                    </label>
                    <input
                      type="text"
                      value={editingItem.name}
                      onChange={(e) => setEditingItem({ ...editingItem, name: e.target.value })}
                      className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 text-sm font-semibold outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                      Category
                    </label>
                    <div className="relative">
                      <select
                        value={editingItem.category}
                        onChange={(e) => setEditingItem({ ...editingItem, category: e.target.value })}
                        className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 pr-10 text-sm font-semibold outline-none appearance-none cursor-pointer"
                      >
                        {Object.keys(CATEGORY_MAP).map(catKey => (
                          <option key={catKey} value={catKey}>{catKey}</option>
                        ))}
                      </select>
                      <div className="absolute right-3 top-3 text-stone-400 pointer-events-none">
                        <ChevronDown size={14} />
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                        Quantity
                      </label>
                      <input
                        type="number"
                        step="any"
                        value={editingItem.quantity}
                        onChange={(e) => setEditingItem({ ...editingItem, quantity: parseFloat(e.target.value) || 1 })}
                        className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 text-sm font-semibold outline-none"
                        required
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                        Unit
                      </label>
                      <input
                        type="text"
                        value={editingItem.unit}
                        onChange={(e) => setEditingItem({ ...editingItem, unit: e.target.value })}
                        className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 text-sm font-semibold outline-none"
                        placeholder="pcs, box, lb"
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                      Estimated Unit Price ($)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={editingItem.priceEstimated}
                      onChange={(e) => setEditingItem({ ...editingItem, priceEstimated: parseFloat(e.target.value) || 0.00 })}
                      className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 text-sm font-semibold outline-none"
                      required
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold uppercase tracking-wider text-stone-400 mb-1.5">
                      Personal Notes
                    </label>
                    <textarea
                      value={editingItem.notes || ""}
                      onChange={(e) => setEditingItem({ ...editingItem, notes: e.target.value })}
                      rows={3}
                      className="w-full bg-[#FAF9F6] border border-stone-200 focus:border-emerald-600 rounded-lg py-2 px-3.5 text-sm font-semibold outline-none resize-none"
                      placeholder="e.g. Choose ripe, pre-sliced, etc."
                    />
                  </div>
                </form>
              </div>

              <div className="space-y-2 border-t border-stone-100 pt-4 bg-white">
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  className="w-full bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-sm py-2.5 rounded-lg transition-colors flex items-center justify-center gap-1.5 shadow-sm shadow-emerald-700/10"
                >
                  <Check size={16} strokeWidth={2.5} />
                  <span>Save Item Configuration</span>
                </button>
                <button
                  type="button"
                  onClick={() => setEditingItem(null)}
                  className="w-full bg-stone-100 hover:bg-stone-200 text-stone-700 font-bold text-sm py-2.5 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Collapsible Developer Console (AI Logs and Payload details) */}
      <AnimatePresence>
        {showDevLogs && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="bg-stone-900 border-t border-stone-800 text-stone-200 z-30 overflow-hidden"
          >
            <div className="max-w-7xl mx-auto p-4 sm:p-6 flex flex-col gap-3">
              <div className="flex justify-between items-center border-b border-stone-800 pb-3">
                <div className="flex items-center gap-2">
                  <Cpu className="text-emerald-400" size={16} />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-stone-100">AI Engine Live Developer Terminal</h4>
                </div>
                <button 
                  onClick={() => setShowDevLogs(false)}
                  className="text-stone-400 hover:text-stone-200 text-xs font-medium"
                >
                  Minimize Terminal
                </button>
              </div>

              <div className="max-h-60 overflow-y-auto space-y-4 font-mono text-xs">
                {aiLogs.length === 0 ? (
                  <p className="text-stone-500 italic py-4">
                    No API transactions logged yet. Add items to your list or generate meal plans to view live Gemini payloads.
                  </p>
                ) : (
                  aiLogs.map((log, i) => (
                    <div key={i} className="bg-stone-950/70 border border-stone-800 rounded-lg p-3">
                      <div className="flex justify-between items-start gap-4 border-b border-stone-900 pb-1.5 mb-2 text-[10px]">
                        <span className="font-bold text-emerald-400 uppercase tracking-widest">{log.type}</span>
                        <span className="text-stone-500">{log.timestamp}</span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <p className="text-[10px] text-stone-400 uppercase font-bold tracking-wider mb-1">Request Endpoint / Prompts:</p>
                          <pre className="bg-stone-950 p-2 rounded border border-stone-900 overflow-x-auto text-[11px] whitespace-pre-wrap leading-relaxed text-stone-300">
                            {log.request}
                          </pre>
                        </div>
                        <div>
                          <p className="text-[10px] text-stone-400 uppercase font-bold tracking-wider mb-1">Returned JSON Response (gemini-3.1-flash-lite):</p>
                          <pre className="bg-stone-950 p-2 rounded border border-stone-900 overflow-x-auto text-[11px] leading-relaxed text-emerald-300/90">
                            {JSON.stringify(log.response, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Simple Footer */}
      <footer className="bg-white border-t border-stone-200 py-6 px-4 mt-auto">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4 text-xs text-stone-400 font-medium">
          <p>© 2026 ListMate Grocery Planner. Built with Gemini 3.5 Flash Lite.</p>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Full-Stack Mode Connected</span>
            </span>
          </div>
        </div>
      </footer>

    </div>
  );
}
