# Early Adopter Lifetime Membership Limit (25 Households)

## Overview
To maintain exclusivity and sustainability of ListMate's premium offering, the early adopter lifetime membership threshold has been updated from **100 households** to **25 households**.

---

## Technical Details

### 1. Backend Threshold Updates
- **`shared/auth.py`**: Updated household count check from `< 100` to `< 25` when determining early adopter status (`is_early`) upon registration.
- **`app.py`**: Updated early adopter verification logic (`int(hhid) <= 25`) across endpoints.

### 2. Frontend UI & Badges
- **`static/settings.html`**, **`static/index.html`** (and mobile client public assets): Updated early adopter badge text from `(Household #X of 100)` to `(Household #X of 25)` and adjusted JavaScript condition checks (`<= 25`).

---

## Migration & Deployment
- Applied to `staging` via Pull Request workflow.
- Production release to `main` pending manual review or explicit user authorization ("GO").
