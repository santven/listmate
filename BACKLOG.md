# Grocery App — Go-to-Market Backlog

**Business Sponsor:** Venkat Santhanam  
**Sprint Cadence:** Saturday → Friday (weekly)  
**Principle:** Enterprise-grade, no OpenClaw dependency, no LLM in the runtime path.  
**Goal:** iOS + Android app, cloud-hosted, publish-ready.

---

## Epic 1: Cloud Migration (off Pi, onto managed infrastructure)

### US-1.1: Database Migration to PostgreSQL
**As a** platform owner, **I want** to migrate from SQLite to PostgreSQL **so that** the app can handle multiple concurrent users and is not limited by a single-file database.

**Acceptance Criteria:**
- PostgreSQL schema mirrors current SQLite schema with proper types and indexes
- Data migration script runs without downtime
- All existing API queries pass against Postgres
- Connection pooling configured (min 5, max 20)

**Estimated Story Points:** 8

---

### US-1.2: Deploy to Managed Cloud Platform
**As a** platform owner, **I want** the backend hosted on a managed platform (Render or Fly.io) **so that** the app is not dependent on a Raspberry Pi in my house.

**Acceptance Criteria:**
- API deploys from GitHub on push to main
- PostgreSQL is managed by the platform (not self-hosted)
- HTTPS enforced via platform cert or Cloudflare
- Health check endpoint responds within 2 seconds
- Environment variables managed via platform secrets (not .env files)

**Estimated Story Points:** 5

---

### US-1.3: Cloudflare DNS + Domain for Production
**As a** platform owner, **I want** a dedicated domain (not raghavfamily.com) for the public app **so that** the product has its own identity.

**Acceptance Criteria:**
- New domain purchased (e.g., grocerlist.app or similar)
- DNS configured in Cloudflare pointing to cloud platform
- HTTPS enforced with auto-renewing certs
- Old raghavfamily.com still works for personal use during transition

**Estimated Story Points:** 3

---

## Epic 2: Authentication & Multi-Tenancy

### US-2.1: Email + Password Authentication
**As a** new user, **I want** to sign up with my email and password **so that** I don't need a Google account to use the app.

**Acceptance Criteria:**
- Email + password sign-up with validation
- Email verification (OTP or magic link)
- Password reset flow
- Rate limiting on auth endpoints (5 attempts per IP per minute)
- Session management with JWT or server-side sessions with secure cookies

**Estimated Story Points:** 8

---

### US-2.2: Social Login (Google + Apple)
**As a** new user, **I want** to sign in with my Google or Apple account **so that** I can get started without creating a password.

**Acceptance Criteria:**
- Google OAuth sign-in (one-tap or button)
- Apple Sign-In (required for App Store if other social logins exist)
- Existing Google SSO users can link to their migrated accounts
- Apple Sign-In passes App Store review requirements

**Estimated Story Points:** 5

---

### US-2.3: Household Multi-Tenancy
**As a** household member, **I want** to invite my family to a shared household account **so that** we all see the same grocery list and stores.

**Acceptance Criteria:**
- Household creation on first sign-up
- Invite by email or shareable link
- Members can join, leave, be removed
- Each member has their own login but shared household data
- Stores and items scoped to household_id
- Existing household data preserved during migration

**Estimated Story Points:** 5

---

## Epic 3: Mobile App

### US-3.1: React Native or Expo App Shell
**As a** mobile user, **I want** a native mobile app **so that** I can use the grocery list on my phone without opening a browser.

**Acceptance Criteria:**
- App shell loads and communicates with cloud API
- Authentication flow works within the app (OAuth redirects handled)
- App icon, splash screen, and app name configured
- Works on iOS 16+ and Android 12+
- Push notification capability integrated (Firebase)

**Estimated Story Points:** 13

---

### US-3.2: Core Screens (Mobile)
**As a** mobile user, **I want** the same store-based grocery list experience as the web app **so that** I don't lose functionality when switching platforms.

**Acceptance Criteria:**
- Store grid with item counts (mirrors web Home screen)
- Store catalog with category headers and auto-categorization
- Item check-off with visit tracking
- Wiggle suggestion chips for purchase patterns
- Search and add new items to catalog
- Move items between stores
- Bottom navigation: Grocery List, Settings

**Estimated Story Points:** 13

---

### US-3.3: Push Notifications
**As a** shopper, **I want** to receive notifications when my partner adds items to the list **so that** I know what's been added while I'm at the store.

**Acceptance Criteria:**
- Push notification when co-shopper adds item to shared store list
- Notification when all items in a store are checked off
- "You might be running low" push for wiggle suggestions (opt-in)
- User can manage notification preferences per store
- Works on both iOS and Android

**Estimated Story Points:** 5

---

## Epic 4: Enterprise-Grade Polish

### US-4.1: Privacy Policy & Terms of Service
**As a** platform owner, **I want** a privacy policy and ToS linked in the app **so that** we comply with App Store requirements and data protection laws.

**Acceptance Criteria:**
- Privacy policy page hosted at `/privacy`
- Terms of service page hosted at `/terms`
- GDPR/CCPA compliant language
- Cookie/app-data disclosure
- No third-party data sharing clause
- Data deletion request mechanism

**Estimated Story Points:** 3

---

### US-4.2: Account Deletion
**As a** user, **I want** to delete my account and all associated data **so that** I have control over my personal information.

**Acceptance Criteria:**
- "Delete Account" button in Settings
- Confirmation dialog with data deletion scope
- All household data deleted if user is the last member
- User data removed if user leaves a multi-member household
- Confirmation email sent
- Complies with App Store guideline 5.1.1(v)

**Estimated Story Points:** 3

---

### US-4.3: Error Handling & Logging
**As a** platform owner, **I want** structured error logging **so that** I can debug issues without SSH-ing into a server.

**Acceptance Criteria:**
- All API errors return consistent JSON: `{"error": "message", "code": "ERROR_CODE"}`
- Server-side error logging to stdout (captured by platform)
- Client-facing errors are user-friendly (no stack traces)
- 500 errors trigger alert (platform-level or email if configurable)
- Rate limiting headers on all API responses

**Estimated Story Points:** 5

---

### US-4.4: Input Validation & Security
**As a** platform owner, **I want** all user inputs validated and sanitized **so that** the app is not vulnerable to injection or XSS attacks.

**Acceptance Criteria:**
- Server-side validation on all endpoints (not just client)
- SQL injection impossible (parameterized queries everywhere)
- XSS impossible (all user-generated content escaped in API responses)
- CSRF tokens on state-changing endpoints
- Content Security Policy headers
- HTTPS enforced, HSTS header set

**Estimated Story Points:** 5

---

### US-4.5: App Store Listing Assets
**As a** platform owner, **I want** App Store and Play Store listing assets **so that** the app can be submitted for review.

**Acceptance Criteria:**
- App name, subtitle, description (targeting "grocery list" keywords)
- Screenshots for iPhone 6.7", 6.5", 5.5" displays
- Screenshots for Android phone + tablet
- App icon (1024x1024)
- Feature graphic for Play Store
- Privacy policy URL linked in store listing
- App Store Connect + Google Play Console accounts configured

**Estimated Story Points:** 5

---

## Epic 5: Migration & Transition

### US-5.1: Data Export for Personal Instance
**As** Venkat, **I want** to export my household's grocery data from the Pi **so that** I can import it into the new cloud instance.

**Acceptance Criteria:**
- Export script generates JSON of all stores, list_items, store_items, visits
- Sensitive data (auth tokens) excluded from export
- Import script loads data into new cloud instance
- IDs are re-mapped (don't collide with existing cloud data)
- Tested: export from Pi → import to cloud → verify data integrity

**Estimated Story Points:** 3

---

### US-5.2: Cutover Plan
**As** Venkat, **I want** a documented cutover plan **so that** my family doesn't lose access or data during the transition.

**Acceptance Criteria:**
- Step-by-step cutover document
- New app installed and tested before old domain redirects
- Rolling cutover: old app stays live until new app confirmed working
- Domain cutover plan (grocery.raghavfamily.com → new domain with redirect)
- Rollback plan if cloud deployment fails

**Estimated Story Points:** 2

---

## Epic 6: Publish & Launch

### US-6.1: iOS App Store Submission
**As a** platform owner, **I want** the app approved on the Apple App Store **so that** iPhone users can download it.

**Acceptance Criteria:**
- Apple Developer account active ($99/yr)
- App passes App Store review (no crashes, privacy policy, account deletion)
- App Store Connect metadata complete
- TestFlight build for beta testing (friends + family)
- Release build submitted and approved

**Estimated Story Points:** 5

---

### US-6.2: Google Play Store Submission
**As a** platform owner, **I want** the app published on Google Play **so that** Android users can download it.

**Acceptance Criteria:**
- Google Play Developer account active ($25 one-time)
- App passes Play Store review
- Play Console listing complete with all required assets
- Internal testing track for friends/family
- Production release published

**Estimated Story Points:** 3

---

## Epic 7: Operational Readiness

### US-7.1: CI/CD Pipeline
**As a** developer, **I want** automated builds and deployments **so that** pushing to main automatically updates production.

**Acceptance Criteria:**
- GitHub Actions workflow: lint → test → deploy on push to main
- Database migrations run automatically as part of deploy
- Failed builds do not deploy
- Deployment status visible in GitHub
- Rollback mechanism (re-deploy previous commit)

**Estimated Story Points:** 5

---

### US-7.2: Automated Database Backups
**As a** platform owner, **I want** daily automated backups of the production database **so that** data is never lost.

**Acceptance Criteria:**
- Managed Postgres daily backups enabled (platform-level or pg_dump cron)
- Backup retention of at least 7 days
- Backup restore tested and documented
- Alert if backup fails

**Estimated Story Points:** 2

---

### US-7.3: Uptime Monitoring
**As a** platform owner, **I want** to know when the app is down **so that** I can address issues before users notice.

**Acceptance Criteria:**
- Uptime check against `/api/health` every 5 minutes
- Alert (email or push) if app is down for >2 minutes
- Free tier service (e.g., UptimeRobot, BetterStack)

**Estimated Story Points:** 1

---

## Sprint Plan

| Sprint | Dates | Theme | Stories | Points |
|---|---|---|---|---|
| **Sprint 0** | Jul 18-25 | Setup & Design | US-1.3 (domain), Backlog refinement, Architecture decisions | 5 |
| **Sprint 1** | Jul 25 - Aug 1 | Cloud Migration | US-1.1 (Postgres), US-1.2 (Deploy) | 13 |
| **Sprint 2** | Aug 1-8 | Auth | US-2.1 (Email), US-2.2 (Social), US-2.3 (Multi-tenancy) | 18 |
| **Sprint 3** | Aug 8-15 | Mobile Shell | US-3.1 (App shell), US-3.3 (Push) | 18 |
| **Sprint 4** | Aug 15-22 | Mobile Screens | US-3.2 (Core screens) | 13 |
| **Sprint 5** | Aug 22-29 | Polish & Security | US-4.1→4.4 (Privacy, Delete, Errors, Validation) | 16 |
| **Sprint 6** | Aug 29 - Sep 5 | Store Assets & Ops | US-4.5 (Assets), US-7.1 (CI/CD), US-7.2 (Backups), US-7.3 (Monitoring) | 13 |
| **Sprint 7** | Sep 5-12 | Migration & Launch | US-5.1 (Export), US-5.2 (Cutover), US-6.1 (iOS), US-6.2 (Android) | 13 |
| **Total** | 7 weeks | | 19 stories | 109 points |

---

## Actions for Venkat (Sprint 0)
- [x] Choose and purchase domain name → **listmate.app** (pending purchase)
- [x] Decide: Render vs Fly.io for hosting → **Render**
- [ ] Create Apple Developer account ($99/yr) → **Wait until Sprint 5**
- [ ] Create Google Play Developer account ($25) → **Wait until Sprint 5**
- [x] Decide: React Native or Expo for mobile → **React Native**
- [x] Review and approve backlog priorities → **Approved, 7-week plan**
