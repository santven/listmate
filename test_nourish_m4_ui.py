import os
import re
import subprocess
import unittest

INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


class TestNourishM4UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_inline_scripts_valid_js_syntax(self):
        scripts = re.findall(
            r"<script(?![^>]*src=)[^>]*>(.*?)</script>",
            self.html,
            re.DOTALL | re.IGNORECASE,
        )
        self.assertGreaterEqual(len(scripts), 1)
        for idx, script in enumerate(scripts):
            res = subprocess.run(
                ["node", "-e", "new Function(process.argv[1])", script],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"JS syntax error in inline script block #{idx}: {res.stderr}",
            )

    def test_screen_nourish_dom_elements_present(self):
        # 1. Screen container & Privacy header
        self.assertIn('id="screenNourish"', self.html)
        self.assertIn("100% Private to your personal login", self.html)
        self.assertIn('id="nourishBtnToday"', self.html)

        # 2. Date Navigator
        self.assertIn('id="nourishDateNav"', self.html)
        self.assertIn('id="nourishBtnPrevDay"', self.html)
        self.assertIn('id="nourishBtnNextDay"', self.html)
        self.assertIn('id="nourishDateLabel"', self.html)
        self.assertIn('id="nourishDatePicker"', self.html)

        # 3. Macro Dashboard & Hydration
        self.assertIn('id="nourishDashboardCard"', self.html)
        self.assertIn('id="nourishCalRemaining"', self.html)
        self.assertIn('id="nourishCalSub"', self.html)
        self.assertIn('id="nourishCalBudget"', self.html)
        self.assertIn('id="nourishCalConsumed"', self.html)
        self.assertIn('id="nourishCalProgress"', self.html)
        self.assertIn('id="nourishVal_protein"', self.html)
        self.assertIn('id="nourishBar_protein"', self.html)
        self.assertIn('id="nourishVal_carbs"', self.html)
        self.assertIn('id="nourishBar_carbs"', self.html)
        self.assertIn('id="nourishVal_fat"', self.html)
        self.assertIn('id="nourishBar_fat"', self.html)
        self.assertIn('id="nourishVal_fiber"', self.html)
        self.assertIn('id="nourishBar_fiber"', self.html)
        self.assertIn('id="nourishValWater"', self.html)
        self.assertIn('id="nourishTargetWater"', self.html)
        self.assertIn('id="nourishWaterProgress"', self.html)
        self.assertIn("+1 Cup (250ml)", self.html)
        self.assertIn("+500ml", self.html)

        # 4. Food Entry Engine
        self.assertIn('id="nourishEntryCard"', self.html)
        self.assertIn('id="nourishSlot_breakfast"', self.html)
        self.assertIn('id="nourishSlot_lunch"', self.html)
        self.assertIn('id="nourishSlot_dinner"', self.html)
        self.assertIn('id="nourishSlot_snack"', self.html)
        self.assertIn('id="nourishTabSearch"', self.html)
        self.assertIn('id="nourishTabDescribe"', self.html)
        self.assertIn('id="nourishSearchInput"', self.html)
        self.assertIn('id="nourishSearchDropdown"', self.html)
        self.assertIn('id="nourishAmountInput"', self.html)
        self.assertIn('id="nourishUnit_g"', self.html)
        self.assertIn('id="nourishUnit_oz"', self.html)
        self.assertIn('id="nourishUnit_ml"', self.html)
        self.assertIn('id="nourishUnit_serving"', self.html)
        self.assertIn('id="nourishGramPill_50"', self.html)
        self.assertIn('id="nourishGramPill_100"', self.html)
        self.assertIn('id="nourishGramPill_150"', self.html)
        self.assertIn('id="nourishGramPill_200"', self.html)
        self.assertIn('id="nourishGramPill_250"', self.html)
        self.assertIn('id="nourishBtnStepMinus"', self.html)
        self.assertIn('id="nourishBtnStepPlus"', self.html)
        self.assertIn('id="nourishPreviewBar"', self.html)
        self.assertIn('id="nourishBtnLog"', self.html)

        # 5. Describe Plate AI
        self.assertIn('id="nourishDescribeInput"', self.html)
        self.assertIn('id="nourishBtnAnalyzePlate"', self.html)
        self.assertIn('id="nourishAnalyzeLoading"', self.html)
        self.assertIn('id="nourishParsedItems"', self.html)

        # 6. Today's Meal Diary
        self.assertIn('id="nourishDiaryContainer"', self.html)
        self.assertIn('id="nourishDiarySection_breakfast"', self.html)
        self.assertIn('id="nourishSlotSubtotal_breakfast"', self.html)
        self.assertIn('id="nourishSlotItems_breakfast"', self.html)
        self.assertIn('id="nourishDiarySection_lunch"', self.html)
        self.assertIn('id="nourishSlotSubtotal_lunch"', self.html)
        self.assertIn('id="nourishSlotItems_lunch"', self.html)
        self.assertIn('id="nourishDiarySection_dinner"', self.html)
        self.assertIn('id="nourishSlotSubtotal_dinner"', self.html)
        self.assertIn('id="nourishSlotItems_dinner"', self.html)
        self.assertIn('id="nourishDiarySection_snack"', self.html)
        self.assertIn('id="nourishSlotSubtotal_snack"', self.html)
        self.assertIn('id="nourishSlotItems_snack"', self.html)

        # 7. Edit Modal
        self.assertIn('id="nourishEditModal"', self.html)
        self.assertIn('id="nourishEditName"', self.html)
        self.assertIn('id="nourishEditAmount"', self.html)
        self.assertIn('id="nourishEditUnit"', self.html)

        # 8. Goals Modal & Button
        self.assertIn('id="nourishBtnOpenGoals"', self.html)
        self.assertIn('id="nourishGoalsModal"', self.html)
        self.assertIn('id="nourishGoalCalories"', self.html)
        self.assertIn('id="nourishGoalProtein"', self.html)
        self.assertIn('id="nourishGoalCarbs"', self.html)
        self.assertIn('id="nourishGoalFat"', self.html)
        self.assertIn('id="nourishGoalFiber"', self.html)
        self.assertIn('id="nourishGoalWater"', self.html)
        self.assertIn('id="nourishBtnSaveGoals"', self.html)

        # 9. Privacy, Household Sharing & User Disable Views
        self.assertIn('id="nourishDisabledView"', self.html)
        self.assertIn('id="nourishActiveView"', self.html)
        self.assertIn('id="nourishPageToggle"', self.html)
        self.assertIn('id="nourishSearchShareHousehold"', self.html)
        self.assertIn('id="nourishDescribeShareHousehold"', self.html)
        self.assertIn('id="nourishBtnShare_breakfast"', self.html)
        self.assertIn('id="nourishBtnShare_lunch"', self.html)
        self.assertIn('id="nourishBtnShare_dinner"', self.html)
        self.assertIn('id="nourishBtnShare_snack"', self.html)
        self.assertIn('id="nourishSharedMealDrawer"', self.html)
        self.assertIn('id="nourishBtnAddSharedMeal"', self.html)

    def test_user_requested_ai_estimating_copy(self):
        # User requested pill badge and removed redundant subline
        self.assertIn("✨ AI Estimating · Check back in ~1 hr", self.html)
        self.assertNotIn("Nutrition available in ~1 hr", self.html)

    def test_runtime_behavior_in_node_sandbox(self):
        node_test = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');

function extractFunction(src, name) {
  const idx = src.indexOf('function ' + name);
  const asyncIdx = src.indexOf('async function ' + name);
  const start = (asyncIdx !== -1 && (idx === -1 || asyncIdx < idx)) ? asyncIdx : idx;
  if (start === -1) throw new Error('Function not found: ' + name);
  let braceDepth = 0;
  let started = false;
  for (let i = start; i < src.length; i++) {
    if (src[i] === '{') { braceDepth++; started = true; }
    else if (src[i] === '}') {
      braceDepth--;
      if (started && braceDepth === 0) {
        return src.slice(start, i + 1);
      }
    }
  }
  throw new Error('Unbalanced braces for ' + name);
}

const fns = [
  'formatNourishDisplayDate',
  'formatNourishShortDate',
  'navigateNourishDate',
  'onNourishDateChange',
  'jumpNourishToToday',
  'selectNourishSlot',
  'switchNourishEntryTab',
  'setNourishUnit',
  'setNourishGramPill',
  'updateNourishGramPillActiveState',
  'stepNourishAmount',
  'onNourishSearchInput',
  'searchNourishCatalog',
  'selectNourishCatalogItemByIndex',
  'selectNourishCatalogItem',
  'updateNourishPreview',
  'submitNourishLog',
  'analyzeNourishPlate',
  'logAllAnalyzedNourishItems',
  'quickAddNourishWater',
  'loadNourishDay',
  'renderNourishDay',
  'renderNourishSlotSection',
  'deleteNourishLog',
  'openNourishEditModal',
  'closeNourishEditModal',
  'saveNourishEditLog',
  'openNourishGoalsModal',
  'closeNourishGoalsModal',
  'saveNourishGoals',
  'isNourishEnabled',
  'setNourishEnabled',
  'updateNourishEnabledView',
  'syncNourishEnabledFromServer',
  'shareNourishMealSlot',
  'checkNourishSharedMeals',
  'openNourishSharedMealDrawer',
  'closeNourishSharedMealDrawer',
  'dismissNourishSharedMeal',
  'acceptNourishSharedMeal'
].map(n => extractFunction(html, n)).join('\n\n');

const elements = {};
function makeEl(id) {
  const classes = new Set();
  return {
    id,
    textContent: '',
    innerHTML: '',
    value: '',
    style: { display: '', width: '', background: '', color: '' },
    attrs: {},
    disabled: false,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    classList: {
      add(c) { classes.add(c); },
      remove(c) { classes.delete(c); },
      contains(c) { return classes.has(c); },
      toggle(c, force) {
        const next = typeof force === 'boolean' ? force : !classes.has(c);
        if (next) classes.add(c); else classes.delete(c);
        return next;
      }
    }
  };
}

const elementIds = [
  'nourishBtnToday', 'nourishDateNav', 'nourishBtnPrevDay', 'nourishBtnNextDay',
  'nourishDateLabel', 'nourishDatePicker', 'nourishDashboardCard',
  'nourishBtnOpenGoals', 'nourishGoalsModal', 'nourishGoalCalories', 'nourishGoalProtein',
  'nourishGoalCarbs', 'nourishGoalFat', 'nourishGoalFiber', 'nourishGoalWater', 'nourishBtnSaveGoals',
  'nourishCalRemaining', 'nourishCalSub', 'nourishCalBudget', 'nourishCalConsumed', 'nourishCalProgress',
  'nourishVal_protein', 'nourishTarget_protein', 'nourishBar_protein',
  'nourishVal_carbs', 'nourishTarget_carbs', 'nourishBar_carbs',
  'nourishVal_fat', 'nourishTarget_fat', 'nourishBar_fat',
  'nourishVal_fiber', 'nourishTarget_fiber', 'nourishBar_fiber',
  'nourishValWater', 'nourishTargetWater', 'nourishWaterProgress',
  'nourishEntryCard', 'nourishSlot_breakfast', 'nourishSlot_lunch', 'nourishSlot_dinner', 'nourishSlot_snack',
  'nourishTabSearch', 'nourishTabDescribe', 'nourishContentSearch', 'nourishContentDescribe',
  'nourishSearchInput', 'nourishSearchDropdown', 'nourishAmountInput',
  'nourishUnit_g', 'nourishUnit_oz', 'nourishUnit_ml', 'nourishUnit_serving',
  'nourishGramPillsRow',
  'nourishGramPill_50', 'nourishGramPill_100', 'nourishGramPill_150', 'nourishGramPill_200', 'nourishGramPill_250',
  'nourishBtnStepMinus', 'nourishBtnStepPlus',
  'nourishPreviewBar', 'nourishBtnLog',
  'nourishDescribeInput', 'nourishBtnAnalyzePlate', 'nourishAnalyzeLoading', 'nourishParsedItems', 'nourishBtnLogAllPlate',
  'nourishDiaryContainer',
  'nourishDiarySection_breakfast', 'nourishSlotSubtotal_breakfast', 'nourishSlotItems_breakfast',
  'nourishDiarySection_lunch', 'nourishSlotSubtotal_lunch', 'nourishSlotItems_lunch',
  'nourishDiarySection_dinner', 'nourishSlotSubtotal_dinner', 'nourishSlotItems_dinner',
  'nourishDiarySection_snack', 'nourishSlotSubtotal_snack', 'nourishSlotItems_snack',
  'nourishEditModal', 'nourishEditName', 'nourishEditAmount', 'nourishEditUnit', 'nourishBtnSaveEditLog',
  'nourishDisabledView', 'nourishActiveView', 'nourishPageToggle', 'nourishBtnStart',
  'nourishSearchShareHousehold', 'nourishDescribeShareHousehold',
  'nourishBtnShare_breakfast', 'nourishBtnShare_lunch', 'nourishBtnShare_dinner', 'nourishBtnShare_snack',
  'nourishSharedMealDrawer', 'nourishSharedDrawerSub', 'nourishSharedDrawerItems', 'nourishBtnAddSharedMeal'
];
elementIds.forEach(id => { elements[id] = makeEl(id); });

const storageMap = {};
global.localStorage = {
  getItem(k) { return storageMap[k] !== undefined ? storageMap[k] : null; },
  setItem(k, v) { storageMap[k] = String(v); },
  removeItem(k) { delete storageMap[k]; },
  clear() { for (let k in storageMap) delete storageMap[k]; }
};

const sessionStorageMap = {};
global.sessionStorage = {
  getItem(k) { return sessionStorageMap[k] !== undefined ? sessionStorageMap[k] : null; },
  setItem(k, v) { sessionStorageMap[k] = String(v); },
  removeItem(k) { delete sessionStorageMap[k]; },
  clear() { for (let k in sessionStorageMap) delete sessionStorageMap[k]; }
};

global.window = global;
global.document = {
  getElementById(id) { return elements[id] || null; },
  addEventListener() {}
};
global.escapeHtml = (s) => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
global.toast = () => {};
global.API = '/api';

global.currentNourishDate = '2026-10-19';
global.currentNourishSlot = 'breakfast';
global.currentNourishData = null;
global.selectedNourishItem = null;
global.nourishSelectedUnit = 'g';
global.nourishSearchDebounceTimer = null;
global.nourishEntryMode = 'search';

eval(fns);

(async () => {
  // 1. Date label formatting
  const todayLabel = formatNourishDisplayDate('2026-10-19');
  if (!todayLabel.includes('Today')) throw new Error('Expected Today in display date, got: ' + todayLabel);

  // 2. Slot selection
  selectNourishSlot('lunch');
  if (!elements.nourishSlot_lunch.classList.contains('active')) throw new Error('Expected lunch slot active');
  if (elements.nourishSlot_breakfast.classList.contains('active')) throw new Error('Expected breakfast slot inactive');
  if (!elements.nourishBtnLog.innerHTML.includes('Lunch')) throw new Error('Expected button text for Lunch');

  // 3. Unit switching and Gram pill selection
  setNourishUnit('oz');
  if (!elements.nourishUnit_oz.classList.contains('active')) throw new Error('Expected oz active');
  if (elements.nourishGramPillsRow.style.display !== 'none') throw new Error('Gram pills should hide for oz');

  setNourishGramPill(150);
  if (!elements.nourishUnit_g.classList.contains('active')) throw new Error('Gram pill should switch unit to g');
  if (elements.nourishAmountInput.value !== '150') throw new Error('Gram pill should set input value to 150');
  if (!elements.nourishGramPill_150.classList.contains('active')) throw new Error('150g pill should be active');

  // 3b. Stepper + and - buttons behavior
  setNourishUnit('serving');
  if (elements.nourishAmountInput.value !== '1') throw new Error('Switching to serving should reset default to 1');
  stepNourishAmount(1);
  if (elements.nourishAmountInput.value !== '2') throw new Error('Clicking + on 1 serving should give 2, got: ' + elements.nourishAmountInput.value);
  stepNourishAmount(1);
  if (elements.nourishAmountInput.value !== '3') throw new Error('Clicking + on 2 servings should give 3, got: ' + elements.nourishAmountInput.value);
  stepNourishAmount(-1);
  if (elements.nourishAmountInput.value !== '2') throw new Error('Clicking - on 3 servings should give 2, got: ' + elements.nourishAmountInput.value);
  stepNourishAmount(-1);
  if (elements.nourishAmountInput.value !== '1') throw new Error('Clicking - on 2 servings should give 1, got: ' + elements.nourishAmountInput.value);
  stepNourishAmount(-1);
  if (elements.nourishAmountInput.value !== '0.5') throw new Error('Clicking - on 1 serving should give 0.5, got: ' + elements.nourishAmountInput.value);

  // 4. Live macro preview calculation
  elements.nourishSearchInput.value = 'Steamed Dosai';
  selectedNourishItem = {
    id: 10,
    name: 'Steamed Dosai',
    calories_per_100g: 168,
    protein_per_100g: 4.2,
    carbs_per_100g: 29.5,
    fat_per_100g: 3.8
  };
  elements.nourishAmountInput.value = '200';
  nourishSelectedUnit = 'g';
  updateNourishPreview();
  // 200g should give 168 * 2 = 336 kcal
  if (!elements.nourishPreviewBar.innerHTML.includes('336 kcal')) {
    throw new Error('Expected 336 kcal in preview, got: ' + elements.nourishPreviewBar.innerHTML);
  }

  // 5. Custom unmatched food preview shows user-requested AI estimating badge
  selectedNourishItem = null;
  elements.nourishSearchInput.value = 'Moms Homemade Halwa';
  updateNourishPreview();
  if (!elements.nourishPreviewBar.innerHTML.includes('✨ AI Estimating · Check back in ~1 hr')) {
    throw new Error('Expected AI estimating message in custom food preview');
  }

  // 6. Day render with budget, 4 macros, hydration, and pending status
  renderNourishDay({
    totals: { calories: 850, protein_g: 45, carbs_g: 110, fat_g: 25, fiber_g: 12 },
    goals: { calorie_target: 2000, protein_target_g: 120, carbs_target_g: 220, fat_target_g: 65, fiber_target_g: 30, water_target_ml: 2500 },
    biometrics: { water_ml: 500 },
    logs: [
      { id: 1, meal_slot: 'lunch', name: 'Steamed Dosai', serving_amount: 150, serving_unit: 'g', calories: 252, protein_g: 6.3, carbs_g: 44.2, fat_g: 5.7, ai_enrich_status: 'enriched' },
      { id: 2, meal_slot: 'lunch', name: 'Moms Homemade Halwa', serving_amount: 100, serving_unit: 'g', calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, ai_enrich_status: 'pending' }
    ]
  });

  if (elements.nourishCalRemaining.textContent !== '1150') throw new Error('Expected 1150 cal remaining');
  if (elements.nourishCalBudget.textContent !== '2000') throw new Error('Expected 2000 cal budget');
  if (elements.nourishCalConsumed.textContent !== '850') throw new Error('Expected 850 cal consumed');
  if (elements.nourishVal_protein.textContent !== '45') throw new Error('Expected 45g protein');
  if (elements.nourishValWater.textContent !== '500') throw new Error('Expected 500ml water');

  // Check that the pending item displays the user-requested indicator
  const lunchHtml = elements.nourishSlotItems_lunch.innerHTML;
  if (!lunchHtml.includes('Steamed Dosai')) throw new Error('Expected Steamed Dosai in lunch items');
  if (!lunchHtml.includes('Moms Homemade Halwa')) throw new Error('Expected Moms Homemade Halwa in lunch items');
  if (!lunchHtml.includes('nourish-log-item-pending')) {
    throw new Error('Expected pending food log item to have class nourish-log-item-pending');
  }
  if (!lunchHtml.includes('✨ AI Estimating · Check back in ~1 hr')) {
    throw new Error('Expected AI estimating badge in diary for pending item');
  }
  if (lunchHtml.includes('Nutrition available in ~1 hr')) {
    throw new Error('Found redundant "Nutrition available in ~1 hr" subline which was removed');
  }

  // 7. Hydration quick add
  const allFetchCalls = [];
  global.fetch = (url, opts) => {
    const callObj = {
      url: url,
      opts: opts,
      body: opts && opts.body ? JSON.parse(opts.body) : null
    };
    allFetchCalls.push(callObj);
    return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
  };
  await quickAddNourishWater(250);
  if (elements.nourishValWater.textContent !== '750') throw new Error('Expected 750ml water after adding 250ml');
  if (!allFetchCalls.some(c => c.url.includes('/api/nourish/biometrics'))) {
    throw new Error('Expected fetch call for biometrics water add');
  }

  // 8. User Finding 4, 5, 6: Portion & Food Name rendering (Toast 1 serving, Bread 1 serving, Sambar Rice 250g)
  renderNourishSlotSection('breakfast', [
    { id: 10, food_name: 'Toast', quantity: 1, unit: 'serving', calories: 75, protein_g: 2.5, carbs_g: 13, fat_g: 1.0 },
    { id: 11, food_name: 'Bread', quantity: 1, unit: 'serving', calories: 80, protein_g: 3.0, carbs_g: 14, fat_g: 1.1 }
  ]);
  const bfastHtml = elements.nourishSlotItems_breakfast.innerHTML;
  if (!bfastHtml.includes('Toast')) throw new Error('Expected food name Toast to be visible');
  if (!bfastHtml.includes('1 serving')) throw new Error('Expected 1 serving for Toast, got: ' + bfastHtml);
  if (!bfastHtml.includes('Bread')) throw new Error('Expected food name Bread to be visible');
  if (bfastHtml.includes('undefined')) throw new Error('Found unexpected "undefined" in breakfast slot HTML');

  renderNourishSlotSection('lunch', [
    { id: 12, food_name: 'Sambar Rice', quantity: 250, unit: 'g', calories: 310, protein_g: 7.2, carbs_g: 58, fat_g: 4.5 }
  ]);
  const lunchHtml2 = elements.nourishSlotItems_lunch.innerHTML;
  if (!lunchHtml2.includes('Sambar Rice')) throw new Error('Expected food name Sambar Rice to be visible');
  if (!lunchHtml2.includes('250g')) throw new Error('Expected 250g for Sambar Rice, got: ' + lunchHtml2);
  if (lunchHtml2.includes('undefined')) throw new Error('Found unexpected "undefined" in lunch slot HTML');

  // 9. User Finding 3: Describe Plate Meal Slot Reactivity
  window._lastNourishAnalyzedItems = [
    { food_name: 'Sambar Rice', quantity: 250, unit: 'g', calories: 310 }
  ];
  selectNourishSlot('lunch');
  if (!elements.nourishBtnLogAllPlate.innerHTML.includes('Lunch')) {
    throw new Error('Expected nourishBtnLogAllPlate to reactively show Lunch');
  }
  selectNourishSlot('dinner');
  if (!elements.nourishBtnLogAllPlate.innerHTML.includes('Dinner')) {
    throw new Error('Expected nourishBtnLogAllPlate to reactively show Dinner');
  }
  selectNourishSlot('snack');
  if (!elements.nourishBtnLogAllPlate.innerHTML.includes('Snack')) {
    throw new Error('Expected nourishBtnLogAllPlate to reactively show Snack');
  }

  // 10. User Finding 7: Goals Modal flow
  currentNourishData = {
    goals: {
      calories_target: 2200,
      protein_target_g: 140,
      carbs_target_g: 210,
      fat_target_g: 70,
      fiber_target_g: 32,
      water_target_ml: 2800
    }
  };
  openNourishGoalsModal();
  if (!elements.nourishGoalsModal.classList.contains('active')) throw new Error('Expected nourishGoalsModal active');
  if (elements.nourishGoalCalories.value !== 2200) throw new Error('Expected calorie input populated');
  if (elements.nourishGoalProtein.value !== 140) throw new Error('Expected protein input populated');

  elements.nourishGoalCalories.value = '2400';
  elements.nourishGoalProtein.value = '155';
  await saveNourishGoals();
  const goalsCall = allFetchCalls.find(c => c.url === '/api/nourish/goals');
  if (!goalsCall) throw new Error('Expected fetch call to /api/nourish/goals');
  if (!goalsCall.body || goalsCall.body.calories_target !== 2400) throw new Error('Expected payload with calories_target=2400');
  if (elements.nourishGoalsModal.classList.contains('active')) throw new Error('Modal should be closed after save');

  // 11. User Enable/Disable Nourish
  await setNourishEnabled(false);
  if (isNourishEnabled() !== false) throw new Error('Expected isNourishEnabled to be false');
  if (elements.nourishDisabledView.style.display !== 'block') throw new Error('Expected nourishDisabledView block');
  if (elements.nourishActiveView.style.display !== 'none') throw new Error('Expected nourishActiveView none');

  await setNourishEnabled(true);
  if (isNourishEnabled() !== true) throw new Error('Expected isNourishEnabled to be true');
  if (elements.nourishDisabledView.style.display !== 'none') throw new Error('Expected nourishDisabledView none');
  if (elements.nourishActiveView.style.display !== 'block') throw new Error('Expected nourishActiveView block');

  // 12. Shared Family Meal 1-Tap Drawer
  const sharedMealSample = {
    meal_slot: 'Dinner',
    shared_by_user_id: 10,
    shared_by_name: 'Venkat',
    log_date: '2026-10-19',
    items: [
      { id: 101, food_name: 'Dosa', serving_amount: 3, serving_unit: 'serving', calories: 360 },
      { id: 102, food_name: 'Paneer Burji', serving_amount: 1, serving_unit: 'serving', calories: 280 }
    ]
  };
  openNourishSharedMealDrawer(sharedMealSample);
  if (elements.nourishSharedMealDrawer.style.display !== 'flex') throw new Error('Expected shared meal drawer display flex');
  if (!elements.nourishSharedDrawerSub.textContent.includes('Venkat')) throw new Error('Expected Venkat in drawer subtitle');
  if (!elements.nourishSharedDrawerItems.innerHTML.includes('Dosa')) throw new Error('Expected Dosa in drawer items');
  if (!elements.nourishBtnAddSharedMeal.textContent.includes('Dinner')) throw new Error('Expected Add to My Dinner button text');

  await acceptNourishSharedMeal();
  const acceptCall = allFetchCalls.find(c => c.url === '/api/nourish/logs' && c.body && c.body.meal_slot === 'Dinner');
  if (!acceptCall) throw new Error('Expected /api/nourish/logs call when accepting shared meal');
  if (elements.nourishSharedMealDrawer.style.display !== 'none') throw new Error('Expected drawer hidden after accept');

  // 13. Slot bulk share
  await shareNourishMealSlot('lunch');
  const shareCall = allFetchCalls.find(c => c.url === '/api/nourish/meals/share');
  if (!shareCall) throw new Error('Expected /api/nourish/meals/share fetch call');
  if (shareCall.body.meal_slot !== 'lunch') throw new Error('Expected meal_slot lunch in share call');

  // 14. Issue #682: Unit switching conversion precision
  elements.nourishAmountInput.value = '100';
  nourishSelectedUnit = 'g';
  setNourishUnit('oz');
  if (elements.nourishAmountInput.value !== '3.5') {
    throw new Error('Expected 100g to convert to 3.5 oz, got: ' + elements.nourishAmountInput.value);
  }
  setNourishUnit('g');
  if (elements.nourishAmountInput.value !== '99') {
    throw new Error('Expected 3.5 oz to convert to 99g, got: ' + elements.nourishAmountInput.value);
  }

  // 15. Issue #684: SessionStorage persistence on dismiss
  window._currentSharedMeal = {
    meal_slot: 'Breakfast',
    shared_by_user_id: 42,
    log_date: '2026-10-19',
    items: [{ food_name: 'Idli', serving_amount: 2, serving_unit: 'serving', calories: 120 }]
  };
  dismissNourishSharedMeal();
  const dismissedKey = 'nourish_dismissed_Breakfast_42_2026-10-19';
  if (sessionStorage.getItem(dismissedKey) !== '1') {
    throw new Error('Expected sessionStorage item to be set on dismiss, got: ' + sessionStorage.getItem(dismissedKey));
  }

  // 16. Issue #684: Update enabled view immediately closes drawer when disabled
  elements.nourishSharedMealDrawer.style.display = 'flex';
  await setNourishEnabled(false);
  if (elements.nourishSharedMealDrawer.style.display !== 'none') {
    throw new Error('Expected shared meal drawer to close when Nourish is disabled');
  }

  // 17. Describe Plate 429 rate limit response handling
  global.fetch = () => Promise.resolve({
    status: 429,
    json: () => Promise.resolve({ ok: false, error: 'Daily AI plate analysis limit reached' })
  });
  elements.nourishDescribeInput.value = '3 idlis with sambar';
  await analyzeNourishPlate();
  if (!elements.nourishParsedItems.innerHTML.includes('Daily AI Plate Limit Reached')) {
    throw new Error('Expected 429 limit message in parsed items container, got: ' + elements.nourishParsedItems.innerHTML);
  }
})();
"""
        res = subprocess.run(
            ["node", "-e", node_test, INDEX_HTML_PATH],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode, 0, f"Runtime sandbox test failed: {res.stderr}"
        )

    def test_settings_html_nourish_toggle(self):
        settings_path = os.path.join(os.path.dirname(__file__), "static", "settings.html")
        with open(settings_path, "r", encoding="utf-8") as f:
            settings_html = f.read()

        self.assertIn('id="nourishSettingsCard"', settings_html)
        self.assertIn('id="nourishSettingToggle"', settings_html)
        self.assertIn("initNourishUI", settings_html)
        self.assertIn("toggleNourishSetting", settings_html)
        self.assertIn("/api/user/nourish-enabled", settings_html)
        # Verify duplicate card tag was cleaned up
        self.assertNotIn('<div class="card">\n  <div class="card">', settings_html)
        self.assertNotIn('<div class="card">\n<div class="card">', settings_html)


if __name__ == "__main__":
    unittest.main()
