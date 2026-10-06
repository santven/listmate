#!/usr/bin/env node

/**
 * send_lifetime_premium_email.js
 * 
 * Sends a personalized appreciation & 45-day milestone update email to all
 * Lifetime Premium households on ListMate.
 * 
 * Usage:
 *   node scripts/send_lifetime_premium_email.js --dry-run
 *   node scripts/send_lifetime_premium_email.js --preview
 *   node scripts/send_lifetime_premium_email.js --test-email venragh@gmail.com [--api-key SG.xxx]
 *   node scripts/send_lifetime_premium_email.js --send [--api-key SG.xxx]
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { Client } = require('pg');

const BASE_URL = 'https://grocerlist.app';
const FROM_EMAIL = 'support@grocerlist.app';
const FROM_NAME = 'ListMate';
const REPLY_TO_EMAIL = 'venragh@gmail.com';
const REPLY_TO_NAME = 'Venkat Santhanam (Founder, ListMate)';

async function getDbClient() {
  const dbUrl = process.env.PROD_DB_URL || process.env.DATABASE_URL || process.env.STAGE_DB_URL;
  if (!dbUrl) {
    throw new Error('Database URL not found in environment (PROD_DB_URL, DATABASE_URL, or STAGE_DB_URL)');
  }
  const client = new Client({ connectionString: dbUrl, ssl: { rejectUnauthorized: false } });
  await client.connect();
  return client;
}

async function fetchStats(client) {
  try {
    const hh = await client.query('SELECT COUNT(*) FROM auth_households;');
    const st = await client.query('SELECT COUNT(*) FROM stores;');
    const vi = await client.query('SELECT COUNT(*) FROM store_visits;');
    const seq = await client.query('SELECT last_value FROM list_items_id_seq;');
    
    const totalCreatedItems = parseInt(seq.rows[0].last_value, 10) || 1079;
    return {
      households: parseInt(hh.rows[0].count, 10) || 54,
      items: totalCreatedItems, // 1000+ items created & tracked
      displayItems: '1,000+',
      stores: parseInt(st.rows[0].count, 10) || 143,
      visits: parseInt(vi.rows[0].count, 10) || 102
    };
  } catch (err) {
    console.warn('[Stats] Fallback to verified metrics due to:', err.message);
    return { households: 54, items: 1079, displayItems: '1,000+', stores: 143, visits: 102 };
  }
}

async function fetchPremiumUsers(client) {
  const query = `
    SELECT 
      h.id AS household_id,
      h.name AS household_name,
      h.is_premium,
      h.subscription_status,
      u.id AS user_id,
      u.name AS user_name,
      u.email
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    WHERE h.is_premium = true
      AND u.email IS NOT NULL
      AND TRIM(u.email) != ''
      AND u.email NOT LIKE '%privaterelay.appleid.com%'
    ORDER BY h.id, u.id;
  `;
  const res = await client.query(query);
  return res.rows;
}

function buildEmailHtml(params) {
  const {
    userName = 'Valued Member',
    householdName = 'Your Household',
    userId = null,
    stats = { households: 54, items: 1079, displayItems: '1,000+', stores: 143, visits: 102 }
  } = params;

  const firstName = (userName || 'Friend').trim().split(/\s+/)[0] || 'Friend';
  const hhName = (householdName || 'Your Household').trim();
  const displayItems = stats.displayItems || '1,000+';

  // Deep links
  const appUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?source=email_lifetime_thanks')}`;
  const feedbackUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?action=feedback&source=email_lifetime_thanks')}`;
  const shareUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?action=share&source=email_lifetime_thanks')}`;
  const iosUrl = 'https://apps.apple.com/us/app/grocerlistmate/id6795402710';
  const androidUrl = 'https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share';

  // Stats bar styling
  const itemsPct = 100;
  const storesPct = 38;
  const visitsPct = 28;
  const hhPct = 20;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Thank You from ListMate - 45 Days of Progress & What's New</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1e293b;-webkit-font-smoothing:antialiased;line-height:1.6;">

  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f4f6f8;padding:32px 12px;">
    <tr>
      <td align="center">

        <!-- Main Card -->
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:620px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid #e2e8f0;">
          
          <!-- Header Banner -->
          <tr>
            <td style="background:linear-gradient(135deg, #15803d 0%, #22c55e 100%);padding:36px 32px 30px;text-align:center;color:#ffffff;">
              <div style="display:inline-block;background:rgba(255,255,255,0.22);border-radius:20px;padding:4px 14px;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#f0fdf4;margin-bottom:12px;">
                ⭐ Founding Early Adopter Update
              </div>
              <h1 style="margin:0;font-size:26px;font-weight:800;letter-spacing:-0.5px;line-height:1.25;color:#ffffff;">
                Thank You for Believing in ListMate
              </h1>
              <p style="margin:8px 0 0;font-size:15px;color:#dcfce7;font-weight:500;">
                Celebrating 45 Days Since Launch with Our Lifetime Members
              </p>
            </td>
          </tr>

          <!-- Main Content -->
          <tr>
            <td style="padding:32px 32px 24px;">

              <!-- Personal Appreciation -->
              <p style="margin:0 0 16px;font-size:16px;color:#1e293b;font-weight:600;">
                Hi ${firstName},
              </p>
              <p style="margin:0 0 16px;font-size:15px;color:#334155;line-height:1.65;">
                When we launched ListMate just 45 days ago, our mission was simple: eliminate the everyday chaos of grocery shopping, duplicate purchases, and forgotten ingredients for families.
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#334155;line-height:1.65;">
                You were among the very first to join and back us with a <strong>Lifetime Premium Subscription</strong> for <strong>${hhName}</strong>. Your early belief gave this project life, and we are profoundly grateful for your partnership. You will always have permanent VIP access to every current and upcoming premium feature.
              </p>

              <!-- Stats Section: Bar Chart Style -->
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:22px 20px;margin-bottom:28px;">
                <div style="text-align:center;margin-bottom:18px;">
                  <span style="font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#16a34a;">Community Momentum</span>
                  <h3 style="margin:4px 0 0;font-size:18px;font-weight:700;color:#0f172a;">45 Days by the Numbers</h3>
                  <p style="margin:4px 0 0;font-size:13px;color:#64748b;">Here is what our growing household community has accomplished together so far:</p>
                </div>

                <!-- Bar 1: List Items (1,000+) -->
                <div style="margin-bottom:16px;">
                  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:6px;font-size:13px;font-weight:600;">
                    <tr>
                      <td align="left" style="color:#334155;">📋 Grocery Items Tracked & Managed</td>
                      <td align="right" style="color:#15803d;font-weight:700;">${displayItems} items</td>
                    </tr>
                  </table>
                  <div style="background:#e2e8f0;border-radius:8px;height:12px;overflow:hidden;width:100%;">
                    <div style="background:linear-gradient(90deg, #22c55e, #15803d);height:12px;width:100%;border-radius:8px;"></div>
                  </div>
                </div>

                <!-- Bar 2: Stores Mapped -->
                <div style="margin-bottom:16px;">
                  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:6px;font-size:13px;font-weight:600;">
                    <tr>
                      <td align="left" style="color:#334155;">🏪 Unique Stores & Grocers Mapped</td>
                      <td align="right" style="color:#2563eb;font-weight:700;">${stats.stores.toLocaleString()} stores</td>
                    </tr>
                  </table>
                  <div style="background:#e2e8f0;border-radius:8px;height:12px;overflow:hidden;width:100%;">
                    <div style="background:linear-gradient(90deg, #60a5fa, #2563eb);height:12px;width:${storesPct}%;border-radius:8px;"></div>
                  </div>
                </div>

                <!-- Bar 3: Store Shopping Trips -->
                <div style="margin-bottom:16px;">
                  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:6px;font-size:13px;font-weight:600;">
                    <tr>
                      <td align="left" style="color:#334155;">🛒 Store Shopping Runs Completed</td>
                      <td align="right" style="color:#d97706;font-weight:700;">${stats.visits.toLocaleString()} trips</td>
                    </tr>
                  </table>
                  <div style="background:#e2e8f0;border-radius:8px;height:12px;overflow:hidden;width:100%;">
                    <div style="background:linear-gradient(90deg, #fbbf24, #d97706);height:12px;width:${visitsPct}%;border-radius:8px;"></div>
                  </div>
                </div>

                <!-- Bar 4: Households -->
                <div style="margin-bottom:4px;">
                  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:6px;font-size:13px;font-weight:600;">
                    <tr>
                      <td align="left" style="color:#334155;">🏡 Total Active Households</td>
                      <td align="right" style="color:#9333ea;font-weight:700;">${stats.households.toLocaleString()} families</td>
                    </tr>
                  </table>
                  <div style="background:#e2e8f0;border-radius:8px;height:12px;overflow:hidden;width:100%;">
                    <div style="background:linear-gradient(90deg, #c084fc, #9333ea);height:12px;width:${hhPct}%;border-radius:8px;"></div>
                  </div>
                </div>
              </div>

              <!-- Product Highlights -->
              <div style="margin-bottom:28px;">
                <div style="font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#16a34a;margin-bottom:4px;">
                  Product Highlights
                </div>
                <h2 style="margin:0 0 16px;font-size:20px;font-weight:700;color:#0f172a;letter-spacing:-0.3px;">
                  What We Built for You in the Last 45 Days
                </h2>
                <p style="margin:0 0 16px;font-size:14px;color:#475569;line-height:1.6;">
                  We have been shipping updates continuously based directly on early adopter feedback. Here are the major highlights now live in your app:
                </p>

                <!-- Feature 1: Instant Trip Alerts -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #16a34a;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    🔔 Instant Trip Alerts & Requester-Only Routing (v1.10.3)
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    When someone finishes shopping, household members who requested those items get an instant push alert. Tapping it opens an interactive purchased items drawer with quantities and checkmarks. An always-on email fallback ensures no one misses what was picked up.
                  </div>
                </div>

                <!-- Feature 2: AI Recipe Planner -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #2563eb;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    🍳 AI Recipe Planner & Ingredient Importer
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Turn leftover fridge ingredients into delicious meal ideas or import recipes directly into your grocery lists categorized aisle-by-aisle.
                  </div>
                </div>

                <!-- Feature 3: Plan a Store Visit (Replaces Multi-store catalog) -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #d97706;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    🗓️ Plan a Store Visit & Trip Scheduling
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Coordinate household shopping runs ahead of time. Schedule store visits, assign who is heading to the grocer, and track completed trips so everyone stays aligned before stepping out the door.
                  </div>
                </div>

                <!-- Feature 4: Daily Inspiration & Culinary Wisdom (Replaces barcode scanner) -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #9333ea;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    ✨ Daily Inspiration & Culinary Wisdom
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Start your grocery planning inspired! Enjoy curated food proverbs, ancient culinary wisdom, and thoughtful reflections from world cultures and renowned chefs directly on your home screen.
                  </div>
                </div>
              </div>

              <!-- Store Buttons Section -->
              <div style="background:#f1f5f9;border-radius:12px;padding:24px 20px;text-align:center;margin-bottom:28px;">
                <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:6px;">
                  📲 Update to the Latest Version Today
                </div>
                <p style="margin:0 0 16px;font-size:13.5px;color:#475569;line-height:1.5;">
                  Make sure your app is updated to <strong>v1.10.3</strong> to enjoy the newest trip alerts and speed enhancements.
                </p>

                <!-- Custom Styled Store Buttons -->
                <table role="presentation" border="0" cellspacing="0" cellpadding="0" style="margin:0 auto;">
                  <tr>
                    <td style="padding:0 8px 8px 0;">
                      <a href="${iosUrl}" target="_blank" rel="noopener noreferrer" style="background:#000000;color:#ffffff;padding:12px 22px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;box-shadow:0 3px 8px rgba(0,0,0,0.18);white-space:nowrap;">
                        <span style="font-size:16px;margin-right:6px;vertical-align:middle;"></span> Update on App Store
                      </a>
                    </td>
                    <td style="padding:0 0 8px 8px;">
                      <a href="${androidUrl}" target="_blank" rel="noopener noreferrer" style="background:#0f172a;color:#ffffff;border:1px solid #334155;padding:12px 22px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;box-shadow:0 3px 8px rgba(0,0,0,0.18);white-space:nowrap;">
                        <span style="font-size:14px;margin-right:6px;vertical-align:middle;">▶</span> Update on Google Play
                      </a>
                    </td>
                  </tr>
                </table>
              </div>

              <!-- Help Shape What We Build Next (Feedback Deep Link) -->
              <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px;margin-bottom:24px;">
                <h3 style="margin:0 0 6px;font-size:16px;font-weight:700;color:#166534;">
                  💡 Help Shape What We Build Next
                </h3>
                <p style="margin:0 0 14px;font-size:13.5px;color:#274c36;line-height:1.55;">
                  As a Lifetime Member, your input directly guides our weekly roadmap. What is one feature, store enhancement, or improvement that would make ListMate even better for your household?
                </p>
                <div>
                  <a href="${feedbackUrl}" target="_blank" rel="noopener noreferrer" style="background:#16a34a;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;box-shadow:0 2px 6px rgba(22,163,74,0.3);">
                    Share Feedback & Feature Ideas &rarr;
                  </a>
                  <span style="display:block;margin-top:8px;font-size:12px;color:#4b5563;">
                    (Or simply reply directly to this email — I read every response!)
                  </span>
                </div>
              </div>

              <!-- Share with Friends (Share Deep Link) -->
              <div style="background:#fafafa;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:28px;text-align:center;">
                <h3 style="margin:0 0 6px;font-size:16px;font-weight:700;color:#0f172a;">
                  🎁 Share ListMate with Friends & Family
                </h3>
                <p style="margin:0 0 14px;font-size:13.5px;color:#64748b;line-height:1.5;max-width:440px;margin-left:auto;margin-right:auto;">
                  Know another couple, roommate, or family looking to take the stress out of weekly grocery runs? Invite them to try ListMate with your personal link.
                </p>
                <a href="${shareUrl}" target="_blank" rel="noopener noreferrer" style="background:#0f172a;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-size:13.5px;font-weight:700;display:inline-block;">
                  Share App with Friends &rarr;
                </a>
              </div>

              <!-- Sign-off -->
              <div style="border-top:1px solid #e2e8f0;padding-top:20px;">
                <p style="margin:0 0 6px;font-size:15px;color:#334155;line-height:1.6;">
                  Thank you once again for your early trust and partnership. We have big plans ahead, and we are thrilled to build ListMate alongside you!
                </p>
                <p style="margin:16px 0 0;font-size:15px;color:#1e293b;font-weight:600;">
                  Warm regards,<br>
                  <span style="color:#0f172a;font-weight:800;">Venkat & The ListMate Team</span><br>
                  <span style="font-size:13px;color:#64748b;font-weight:400;">Founder, ListMate (<a href="${BASE_URL}" style="color:#16a34a;text-decoration:none;">grocerlist.app</a>)</span>
                </p>
              </div>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;font-size:12px;color:#94a3b8;line-height:1.5;">
              <p style="margin:0 0 6px;">
                You are receiving this special founding member update because you have Lifetime Premium Access with ListMate.
              </p>
              <p style="margin:0;">
                <a href="${appUrl}" style="color:#16a34a;text-decoration:none;font-weight:600;">Open ListMate</a> &bull; 
                <a href="${feedbackUrl}" style="color:#64748b;text-decoration:none;">Send Feedback</a> &bull; 
                <a href="https://grocerlist.app/privacy" style="color:#64748b;text-decoration:none;">Privacy Policy</a>
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>`;
}

function buildPlainText(params) {
  const {
    userName = 'Valued Member',
    householdName = 'Your Household',
    stats = { households: 54, items: 1079, displayItems: '1,000+', stores: 143, visits: 102 }
  } = params;

  const firstName = (userName || 'Friend').trim().split(/\s+/)[0] || 'Friend';
  const hhName = (householdName || 'Your Household').trim();
  const displayItems = stats.displayItems || '1,000+';

  const appUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?source=email_lifetime_thanks')}`;
  const feedbackUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?action=feedback&source=email_lifetime_thanks')}`;
  const shareUrl = `${BASE_URL}/open?url=${encodeURIComponent('/?action=share&source=email_lifetime_thanks')}`;
  const iosUrl = 'https://apps.apple.com/us/app/grocerlistmate/id6795402710';
  const androidUrl = 'https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share';

  return `Hi ${firstName},

When we launched ListMate just 45 days ago, our mission was simple: eliminate the everyday chaos of grocery shopping, duplicate purchases, and forgotten ingredients for families.

You were among the very first to join and back us with a Lifetime Premium Subscription for ${hhName}. Your early belief gave this project life, and we are profoundly grateful for your partnership. You will always have permanent VIP access to every current and upcoming premium feature.

==================================================
📊 45 DAYS BY THE NUMBERS
==================================================
Here is what our growing household community has accomplished together so far:

• 📋 Grocery Items Tracked & Managed: ${displayItems} items
• 🏪 Unique Stores & Grocers Mapped: ${stats.stores.toLocaleString()} stores
• 🛒 Store Shopping Runs Completed: ${stats.visits.toLocaleString()} trips
• 🏡 Total Active Households: ${stats.households.toLocaleString()} families

==================================================
✨ WHAT WE BUILT FOR YOU IN THE LAST 45 DAYS
==================================================

1. Instant Trip Alerts & Requester-Only Routing (v1.10.3)
When someone finishes shopping, household members who requested those items get an instant push alert. Tapping it opens an interactive purchased items drawer with quantities and checkmarks. An always-on email fallback ensures no one misses what was picked up.

2. AI Recipe Planner & Ingredient Importer
Turn leftover fridge ingredients into delicious meal ideas or import recipes directly into your grocery lists categorized aisle-by-aisle.

3. Plan a Store Visit & Trip Scheduling
Coordinate household shopping runs ahead of time. Schedule store visits, assign who is heading to the grocer, and track completed trips so everyone stays aligned before stepping out the door.

4. Daily Inspiration & Culinary Wisdom
Start your grocery planning inspired! Enjoy curated food proverbs, ancient culinary wisdom, and thoughtful reflections from world cultures and renowned chefs directly on your home screen.

==================================================
📲 UPDATE TO THE LATEST VERSION (v1.10.3)
==================================================
• Apple App Store: ${iosUrl}
• Google Play Store: ${androidUrl}

==================================================
💡 HELP SHAPE WHAT WE BUILD NEXT
==================================================
As a Lifetime Member, your input guides our product roadmap. What is one feature, store enhancement, or improvement that would make ListMate even better for your household?

Share Feedback: ${feedbackUrl}
(Or simply reply directly to this email — I read every response!)

==================================================
🎁 SHARE LISTMATE WITH FRIENDS
==================================================
Know another couple, roommate, or family looking to take the stress out of weekly grocery runs? Invite them to try ListMate:
${shareUrl}

Thank you once again for your early trust and partnership!

Warm regards,
Venkat & The ListMate Team
Founder, ListMate (https://grocerlist.app)
`;
}

function sendSendGridEmail(apiKey, payload) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload);
    const req = https.request({
      hostname: 'api.sendgrid.com',
      path: '/v3/mail/send',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data)
      }
    }, res => {
      let respBody = '';
      res.on('data', chunk => respBody += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(true);
        } else {
          reject(new Error(`SendGrid failed with status ${res.statusCode}: ${respBody}`));
        }
      });
    });

    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

async function main() {
  const args = process.argv.slice(2);
  const isPreview = args.includes('--preview');
  const isDryRun = args.includes('--dry-run');
  const isSend = args.includes('--send');
  const testIdx = args.indexOf('--test-email');
  const testEmail = testIdx !== -1 ? args[testIdx + 1] : null;

  const keyIdx = args.indexOf('--api-key');
  const apiKey = (keyIdx !== -1 ? args[keyIdx + 1] : null) || process.env.SENDGRID_API_KEY;

  const client = await getDbClient();
  const stats = await fetchStats(client);
  const users = await fetchPremiumUsers(client);

  console.log(`\n==================================================`);
  console.log(`🎉 ListMate Lifetime Premium Email Automation`);
  console.log(`==================================================`);
  console.log(`• Platform Stats: ${stats.households} households, ${stats.displayItems} items, ${stats.stores} stores, ${stats.visits} visits`);
  console.log(`• Total Premium Users found: ${users.length}`);

  if (isPreview || (!isDryRun && !isSend && !testEmail)) {
    const previewHtml = buildEmailHtml({
      userName: 'Venkat Santhanam',
      householdName: 'Raghav Household',
      stats
    });
    const previewPath = path.join(__dirname, '..', 'static', 'preview_lifetime_email.html');
    fs.writeFileSync(previewPath, previewHtml);
    console.log(`\n✅ Generated HTML preview file at:`);
    console.log(`   ${previewPath}`);
    console.log(`   Preview in browser: /preview_lifetime_email.html\n`);
  }

  if (isDryRun) {
    console.log(`\n📋 DRY RUN RECIPIENTS (${users.length} total):`);
    users.forEach((u, i) => {
      console.log(`  ${i + 1}. [HH #${u.household_id}] ${u.household_name} | ${u.user_name} <${u.email}>`);
    });
    console.log(`\n--- SAMPLE SUBJECT ---`);
    console.log(`⭐ Thank you for being an early adopter of ListMate (+ 45-day milestone & what's new)`);
    console.log(`\n--- SAMPLE PLAIN TEXT ---`);
    console.log(buildPlainText({
      userName: users[0]?.user_name || 'Venkat Santhanam',
      householdName: users[0]?.household_name || 'Raghav Household',
      stats
    }));
  }

  if (testEmail) {
    if (!apiKey) {
      console.error(`\n❌ Error: SENDGRID_API_KEY is required to send test email. Provide via --api-key SG.xxx or env var.`);
      process.exit(1);
    }
    console.log(`\n🚀 Sending test email to: ${testEmail}...`);
    const subject = `⭐ Thank you for being an early adopter of ListMate (+ 45-day milestone & what's new)`;
    const html = buildEmailHtml({
      userName: 'Early Adopter',
      householdName: 'Test Household',
      stats
    });
    const text = buildPlainText({
      userName: 'Early Adopter',
      householdName: 'Test Household',
      stats
    });

    const payload = {
      from: { email: FROM_EMAIL, name: FROM_NAME },
      reply_to: { email: REPLY_TO_EMAIL, name: REPLY_TO_NAME },
      personalizations: [{
        to: [{ email: testEmail, name: 'Early Adopter' }],
        custom_args: { campaign: 'lifetime_premium_thanks_test' }
      }],
      subject,
      content: [
        { type: 'text/plain', value: text },
        { type: 'text/html', value: html }
      ]
    };

    await sendSendGridEmail(apiKey, payload);
    console.log(`✅ Test email successfully dispatched to ${testEmail}!`);
  }

  if (isSend) {
    if (!apiKey) {
      console.error(`\n❌ Error: SENDGRID_API_KEY is required to dispatch batch emails. Provide via --api-key SG.xxx or env var.`);
      process.exit(1);
    }

    console.log(`\n🚀 DISPATCHING TO ALL ${users.length} PREMIUM USERS...`);
    let sentCount = 0;
    for (const u of users) {
      const subject = `⭐ Thank you for being an early adopter of ListMate (+ 45-day milestone & what's new)`;
      const html = buildEmailHtml({
        userName: u.user_name,
        householdName: u.household_name,
        userId: u.user_id,
        stats
      });
      const text = buildPlainText({
        userName: u.user_name,
        householdName: u.household_name,
        stats
      });

      const payload = {
        from: { email: FROM_EMAIL, name: FROM_NAME },
        reply_to: { email: REPLY_TO_EMAIL, name: REPLY_TO_NAME },
        personalizations: [{
          to: [{ email: u.email, name: u.user_name || 'Member' }],
          custom_args: {
            user_id: String(u.user_id),
            household_id: String(u.household_id),
            campaign: 'lifetime_premium_thanks'
          }
        }],
        subject,
        content: [
          { type: 'text/plain', value: text },
          { type: 'text/html', value: html }
        ]
      };

      try {
        await sendSendGridEmail(apiKey, payload);
        sentCount++;
        console.log(`  [${sentCount}/${users.length}] Sent to: ${u.email} (${u.household_name})`);
      } catch (sendErr) {
        console.error(`  [FAILED] ${u.email}:`, sendErr.message);
      }
    }
    console.log(`\n🎉 Finished! Dispatched ${sentCount} of ${users.length} emails.`);
  }

  await client.end();
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
