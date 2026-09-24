/**
 * Discounting as a grantable permission, and the silent-strip bug it nearly shipped with.
 *
 * The last check is the important one: saving a member's access through the UI must not quietly
 * remove a permission the page did not know about. That is what a hard-coded feature list caused,
 * and why the list is served by the API.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const SELLER = process.env.E2E_SELLER ?? "seller";
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
  await page.waitForLoadState("networkidle");
  return page;
}

async function call(page, url, options = {}) {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "csrftoken")?.value;
  return page.evaluate(
    async ({ target, opts, token }) => {
      const r = await fetch(target, {
        ...opts,
        headers: { "Content-Type": "application/json", "X-CSRFToken": token, ...(opts.headers || {}) },
        credentials: "include",
      });
      return { status: r.status, body: await r.text() };
    },
    { target: url, opts: options, token: csrf },
  );
}

const owner = await signIn(OWNER);

// Start from a known state: a previous run may have granted the permission, and a test that only
// passes on a fresh database is a test that will fail in CI for the wrong reason.
const staffBefore = JSON.parse((await call(owner, "/api/staff/")).body).find((m) => m.username === SELLER);
await call(owner, `/api/staff/${staffBefore.id}/`, {
  method: "PATCH",
  body: JSON.stringify({ permissions: staffBefore.permissions.filter((p) => p !== "discount") }),
});

// The catalogue price we will try to undercut.
const types = JSON.parse((await call(owner, "/api/cable-types/")).body);
const size = types.flatMap((t) => t.sizes)[0];
const catalogue = Number(size.default_price);
const quoteBody = (price) =>
  JSON.stringify({
    customer_name: "Discount Test",
    staff_name: "Seller",
    line_items: [
      {
        kind: "cable",
        cable_size: size.id,
        cable_type_name: "Singles",
        size_label: size.size_label,
        unit: "coil",
        unit_price: String(price),
        colours: [{ colour: "", quantity: 1 }],
      },
    ],
  });

// --- a seller without the permission is held to the catalogue price ---
const seller = await signIn(SELLER);
const refused = await call(seller, "/api/quotes/", { method: "POST", body: quoteBody(catalogue * 0.7) });
check("a seller without the permission cannot undercut", refused.status, 400);
check("the refusal names the catalogue", refused.body.includes("catalogue"), true);
check(
  "selling at the catalogue price is fine",
  (await call(seller, "/api/quotes/", { method: "POST", body: quoteBody(catalogue) })).status,
  201,
);

// --- the owner grants it from the staff screen ---
await owner.goto(`${BASE}/staff`, { waitUntil: "networkidle" });
const row = owner.locator(".member", { hasText: SELLER });
await row.locator(".member-head").click();
const discountBox = row
  .locator(".permission-option", { hasText: "Sell below the catalogue price" })
  .locator("input");
await discountBox.waitFor({ timeout: 10000 });
check("the discount permission is offered in the UI", await discountBox.count(), 1);
check("it is off for this seller", await discountBox.isChecked(), false);

await discountBox.check();
await row.getByRole("button", { name: /save access/i }).click();
// The panel collapses only once the save succeeds, so that is the signal to wait on. Network idle
// can settle before the PATCH has been applied.
await row.locator(".member-body").waitFor({ state: "detached", timeout: 15000 });

// --- and now they can ---
const allowed = await call(seller, "/api/quotes/", { method: "POST", body: quoteBody(catalogue * 0.7) });
check("granting it lets them discount", allowed.status, 201);

const activity = await call(owner, "/api/activity/");
check("the discount is recorded against them", activity.body.includes("instead of"), true);

// --- the silent-strip regression ---
const before = JSON.parse((await call(owner, "/api/staff/")).body).find((m) => m.username === SELLER);
await owner.reload({ waitUntil: "networkidle" });
const row2 = owner.locator(".member", { hasText: SELLER });
await row2.locator(".member-head").click();
await row2.getByRole("button", { name: /save access/i }).click();
await row2.locator(".member-body").waitFor({ state: "detached", timeout: 15000 });
const after = JSON.parse((await call(owner, "/api/staff/")).body).find((m) => m.username === SELLER);
check(
  "saving without changing anything keeps every permission",
  JSON.stringify(after.permissions.sort()),
  JSON.stringify(before.permissions.sort()),
);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nDiscount permission browser check passed.");
