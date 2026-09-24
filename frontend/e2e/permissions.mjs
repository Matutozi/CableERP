/**
 * Enforcement, in a real browser, as a real sales member.
 *
 * The unit suite walks the URL conf server-side. This walks it through the app's own origin with a
 * real session cookie, because the thing that actually reaches a customer is what the browser can
 * fetch — not what a test client can.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const SELLER = process.env.E2E_SELLER ?? "seller";
const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";
const ACCOUNT_NUMBER = "0125277464";

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);

async function signIn(username) {
  const page = await browser.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 });
  return page;
}

const get = (page, url) =>
  page.evaluate(async (target) => {
    const r = await fetch(target, { credentials: "include" });
    return { status: r.status, body: r.ok ? await r.text() : "" };
  }, url);

// --- as a sales member ---
const seller = await signIn(SELLER);

const catalogue = await get(seller, "/api/cable-types/");
check("sales can read the catalogue", catalogue.status, 200);
check("no cost in the catalogue", catalogue.body.includes("last_unit_cost"), false);
check("no margin in the catalogue", catalogue.body.includes("margin_percentage"), false);

const quotes = await get(seller, "/api/quotes/");
check("sales can read quotes", quotes.status, 200);
check("no margin on quotes", quotes.body.includes("total_margin"), false);

const movements = await get(seller, "/api/price-movements/");
check("price movements reachable", movements.status, 200);
check("no cost series on the dashboard", movements.body.includes("last_unit_cost"), false);

const profile = await get(seller, "/api/profile/");
check("profile reachable", profile.status, 200);
check("no account number on the profile", profile.body.includes(ACCOUNT_NUMBER), false);

const activity = await get(seller, "/api/activity/");
check("no account number in the activity log", activity.body.includes(ACCOUNT_NUMBER), false);

check("the purchase ledger is refused", (await get(seller, "/api/purchases/")).status, 403);

// --- the same routes as the owner, to prove the gate reads permissions ---
const owner = await signIn(OWNER);
const ownerCatalogue = await get(owner, "/api/cable-types/");
check("the owner still sees cost", ownerCatalogue.body.includes("last_unit_cost"), true);
check("the owner still reaches purchases", (await get(owner, "/api/purchases/")).status, 200);
check(
  "the owner still sees the account number",
  (await get(owner, "/api/profile/")).body.includes(ACCOUNT_NUMBER),
  true,
);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nPermission browser check passed.");
