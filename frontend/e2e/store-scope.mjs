/**
 * Store scoping in a real browser: a member assigned to one branch must not reach another's trade.
 *
 * Signs in as a member scoped to Ikeja who otherwise holds every permission, so anything they
 * cannot see is the store scope doing the work rather than a missing permission.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const BRANCH_STAFF = process.env.E2E_BRANCH_STAFF ?? "branchstaff";
const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";

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

const staff = await signIn(BRANCH_STAFF);

const quotes = await get(staff, "/api/quotes/?page_size=50");
check("their own branch's quote is listed", quotes.body.includes("QT-IKJ-1"), true);
check("another branch's quote is not", quotes.body.includes("QT-ABA-1"), false);
check("a quote with no branch stays visible", quotes.body.includes("QT-OLD-1"), true);

const activity = await get(staff, "/api/activity/");
check("their branch's activity is listed", activity.body.includes("Ikeja sale happened"), true);
check("another branch's activity is not", activity.body.includes("Aba sale happened"), false);

// The owner sees the whole business, which proves the scope is per membership and not global.
const owner = await signIn(OWNER);
const ownerQuotes = await get(owner, "/api/quotes/?page_size=50");
check("the owner sees Ikeja", ownerQuotes.body.includes("QT-IKJ-1"), true);
check("the owner sees Aba", ownerQuotes.body.includes("QT-ABA-1"), true);
check(
  "the owner sees both branches' activity",
  (await get(owner, "/api/activity/")).body.includes("Aba sale happened"),
  true,
);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nStore scope browser check passed.");
