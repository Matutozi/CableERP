/**
 * The branch picker in the header.
 *
 * The check that matters is the last pair: picking a branch must narrow what you see, and must
 * never be able to widen it. A member scoped to one branch should not even be offered the control.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const BRANCH_STAFF = process.env.E2E_BRANCH_STAFF ?? "branchstaff";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);

async function signIn(username) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 });
  // The picker renders nothing until its own fetch resolves, so asserting on it straight after
  // navigation would race the request rather than test the component.
  await page.waitForLoadState("networkidle");
  return page;
}

const quoteRefs = (page) =>
  page.evaluate(async () => {
    const r = await fetch("/api/quotes/?page_size=50", { credentials: "include" });
    const data = await r.json();
    return (data.results ?? data).map((q) => q.reference_number);
  });

// --- an owner with several branches gets the picker ---
const owner = await signIn(OWNER);
const picker = owner.locator(".store-picker select");
// count() does not auto-wait, and the picker renders only once its fetch resolves.
await picker.waitFor({ timeout: 10000 });
check("the owner sees a branch picker", await picker.count(), 1);
check("it offers every branch plus All", (await picker.locator("option").count()) >= 3, true);

const before = await quoteRefs(owner);
check(
  "all branches are visible by default",
  before.includes("QT-ABA-1") && before.includes("QT-IKJ-1"),
  true,
);

// Choosing a branch reloads the page; waiting for the load event rather than the old page's
// network idle is what makes the next read see the new branch.
await Promise.all([owner.waitForEvent("load"), picker.selectOption({ label: "Ikeja" })]);
await owner.waitForLoadState("networkidle");
const after = await quoteRefs(owner);
check("choosing Ikeja hides Aba", after.includes("QT-ABA-1"), false);
check("choosing Ikeja keeps Ikeja", after.includes("QT-IKJ-1"), true);
check(
  "the choice survives the reload",
  (await owner.locator(".store-picker select").inputValue()) !== "all",
  true,
);

await Promise.all([
  owner.waitForEvent("load"),
  owner.locator(".store-picker select").selectOption({ label: "All branches" }),
]);
await owner.waitForLoadState("networkidle");
check("clearing it restores every branch", (await quoteRefs(owner)).includes("QT-ABA-1"), true);

// --- a member scoped to one branch is not offered a choice ---
const staff = await signIn(BRANCH_STAFF);
// Wait for something that proves the page settled, so "absent" cannot mean "not rendered yet".
await staff.locator("nav").first().waitFor({ timeout: 10000 });
check("a single-branch member sees no picker", await staff.locator(".store-picker select").count(), 0);

// ...and cannot select past their membership even by asking directly.
const refused = await staff.evaluate(async () => {
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1];
  const all = await (await fetch("/api/stores/", { credentials: "include" })).json().catch(() => []);
  const r = await fetch("/api/current-store/", {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    credentials: "include",
    body: JSON.stringify({ store: 999999 }),
  });
  return { status: r.status, stores: Array.isArray(all) ? all.length : "refused" };
});
check("selecting a branch they do not have is refused", refused.status, 400);
check("they still cannot see another branch's quote", (await quoteRefs(staff)).includes("QT-ABA-1"), false);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nStore picker browser check passed.");
