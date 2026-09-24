/**
 * The whole product, once, from nothing.
 *
 * A brand-new business registers through the form, builds a catalogue, defines its own role, hires
 * someone, sets what that person may do, and the new hire quotes a customer and raises the waybill
 * that goes out with the goods.
 *
 * Every other suite tests one seam. This one tests that the seams line up: it depends on no seeded
 * data, and each step uses what the previous step actually produced.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const RUN = Date.now().toString(36);
const OWNER = `owner${RUN}`;
const CASHIER = `cashier${RUN}`;
const BUSINESS = `Journey Cables ${RUN}`;
const PASSWORD = "a-strong-pass-123";
const CATALOGUE_PRICE = 33000;

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}
function step(name) {
  console.log(`\n— ${name}`);
}

const browser = await chromium.launch(launchOptions);

async function call(page, url, options = {}) {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "csrftoken")?.value;
  const result = await page.evaluate(
    async ({ target, opts, token }) => {
      const r = await fetch(target, {
        ...opts,
        headers: { "Content-Type": "application/json", "X-CSRFToken": token, ...(opts.headers || {}) },
        credentials: "include",
      });
      const text = await r.text();
      return { status: r.status, text };
    },
    { target: url, opts: options, token: csrf },
  );
  try {
    result.json = JSON.parse(result.text);
  } catch {
    result.json = null;
  }
  return result;
}

// ─────────────────────────────────────────────────────────────── 1. a business signs up
step("A new business signs up");
const ownerCtx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const owner = await ownerCtx.newPage();
// This journey deliberately probes endpoints the employee may not reach, so the browser logs the
// refusals it is meant to get. Only unexpected errors are collected.
const expected = /40[03] \(/;
const ownerErrors = [];
owner.on("console", (m) => m.type() === "error" && !expected.test(m.text()) && ownerErrors.push(m.text()));

await owner.goto(`${BASE}/register`, { waitUntil: "networkidle" });
await owner.locator('input[placeholder*="Acme-Oaks"]').fill(BUSINESS);
await owner.locator('input[autocomplete="username"]').fill(OWNER);
await owner.locator('input[type="password"]').fill(PASSWORD);
await owner.locator('button[type="submit"]').click();
await owner.waitForURL((u) => !u.pathname.includes("register"), { timeout: 20000 });
check("registration signs the owner straight in", !owner.url().includes("register"), true);

// Onboarding must build the whole spine, not just a profile.
const profile = (await call(owner, "/api/profile/")).json;
check("the business exists", profile.business_name, BUSINESS);
check("it starts with one store allowed", profile.store_limit, 1);

const stores = (await call(owner, "/api/stores/")).json;
check("a first branch was created for them", stores.length, 1);
check("it is the Main branch", stores[0].code, "MAIN");

const roles = (await call(owner, "/api/roles/")).json;
check(
  "the default roles are seeded",
  roles
    .map((r) => r.name)
    .sort()
    .join(),
  "Manager,Owner,Sales",
);

const staff = (await call(owner, "/api/staff/")).json;
check("the owner is the only member", staff.length, 1);
check("and is marked as owner", staff[0].is_owner, true);

// ─────────────────────────────────────────────────────────────── 2. they build a catalogue
step("The owner sets up what they sell");
const cableType = await call(owner, "/api/cable-types/", {
  method: "POST",
  body: JSON.stringify({
    name: "Singles",
    unit: "coil",
    has_colour_variants: true,
    colour_options: ["Red", "Black"],
  }),
});
check("a cable type is created", cableType.status, 201);

const size = await call(owner, `/api/cable-types/${cableType.json.id}/sizes/`, {
  method: "POST",
  body: JSON.stringify({
    size_label: "1.5mm",
    default_price: String(CATALOGUE_PRICE),
    factory_price: "40000",
  }),
});
check("a size with a price is created", size.status, 201);
check("and a factory price above it", size.json.factory_saving, "7000.00");

// ─────────────────────────────────────────────────────────────── 3. the org chart is theirs
step("The owner invents a role that suits their business");
const cashierRole = await call(owner, "/api/roles/", {
  method: "POST",
  body: JSON.stringify({ name: "Cashier", permissions: ["catalogue", "quotes", "waybills"] }),
});
check("a business-defined role is created", cashierRole.status, 201);
check("it is not a system role", cashierRole.json.is_system, false);

// ─────────────────────────────────────────────────────────────── 4. they hire someone
step("The owner invites an employee");
const invite = await call(owner, "/api/invitations/", {
  method: "POST",
  body: JSON.stringify({
    phone: "08030000001",
    full_name: "Journey Cashier",
    role_template: cashierRole.json.id,
    all_stores: true,
  }),
});
check("the invitation is created", invite.status, 201);
check("it carries a one-time link", invite.json.invite_url?.startsWith("/invite/"), true);
check("and is pending", invite.json.status, "pending");

step("The employee claims the link and sets their own password");
const staffCtx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const cashier = await staffCtx.newPage();
const cashierErrors = [];
cashier.on(
  "console",
  (m) => m.type() === "error" && !expected.test(m.text()) && cashierErrors.push(m.text()),
);

await cashier.goto(`${BASE}${invite.json.invite_url}`, { waitUntil: "networkidle" });
await cashier.locator('input[autocomplete="name"]').fill("Journey Cashier");
await cashier.locator('input[autocomplete="username"]').fill(CASHIER);
await cashier.locator('input[autocomplete="new-password"]').fill(PASSWORD);
await cashier.getByRole("button", { name: /^join$/i }).click();
await cashier.waitForURL((u) => !u.pathname.includes("invite"), { timeout: 20000 });
check("joining signs them in", !cashier.url().includes("/invite/"), true);

const staffAfter = (await call(owner, "/api/staff/")).json;
check("the owner now has two people", staffAfter.length, 2);
check(
  "the new one carries the invented role",
  staffAfter.find((m) => m.username === CASHIER)?.role_label,
  "Cashier",
);

// ─────────────────────────────────────────────────────────────── 5. what they may and may not do
step("The employee's access is exactly what was granted");
const theirCatalogue = await call(cashier, "/api/cable-types/");
check("they can read the catalogue", theirCatalogue.status, 200);
check("but not what the stock cost", theirCatalogue.text.includes("last_unit_cost"), false);
check("nor the margin", theirCatalogue.text.includes("margin_percentage"), false);
check("they cannot open the purchase ledger", (await call(cashier, "/api/purchases/")).status, 403);
check("they cannot manage staff", (await call(cashier, "/api/staff/")).status, 403);
check(
  "they cannot change the catalogue price",
  (
    await call(cashier, `/api/sizes/${size.json.id}/`, {
      method: "PATCH",
      body: JSON.stringify({ default_price: "1" }),
    })
  ).status,
  403,
);

// ─────────────────────────────────────────────────────────────── 6. they sell something
step("The employee quotes a customer");
const lineItem = (price) => ({
  kind: "cable",
  cable_size: size.json.id,
  cable_type_name: "Singles",
  size_label: "1.5mm",
  unit: "coil",
  unit_price: String(price),
  colours: [
    { colour: "Red", quantity: 3 },
    { colour: "Black", quantity: 2 },
  ],
});

const undercut = await call(cashier, "/api/quotes/", {
  method: "POST",
  body: JSON.stringify({
    customer_name: "Musa Traders",
    staff_name: "Journey Cashier",
    line_items: [lineItem(20000)],
  }),
});
check("they cannot undercut the catalogue price", undercut.status, 400);

const quote = await call(cashier, "/api/quotes/", {
  method: "POST",
  body: JSON.stringify({
    customer_name: "Musa Traders",
    staff_name: "Journey Cashier",
    line_items: [lineItem(CATALOGUE_PRICE)],
  }),
});
check("they can quote at the catalogue price", quote.status, 201);
check("the total is quantity times price", Number(quote.json.subtotal), CATALOGUE_PRICE * 5);
check("the payment account came from the business", quote.json.payment_bank_name !== undefined, true);
check("no margin is shown to them", quote.text.includes("total_margin"), false);

step("The owner sees the quote, and the margin on it");
const ownerView = await call(owner, `/api/quotes/${quote.json.id}/`);
check("the owner can open the same quote", ownerView.status, 200);
check("and does see cost", ownerView.text.includes("unit_cost"), true);

// ─────────────────────────────────────────────────────────────── 7. the goods go out
step("The employee raises the waybill");
const waybill = await call(cashier, "/api/waybills/", {
  method: "POST",
  body: JSON.stringify({ quote: quote.json.id }),
});
check("a waybill is created from the quote", waybill.status, 201);
check("it remembers which quote", waybill.json.quote_reference, quote.json.reference_number);
check("it carries the same colours", waybill.json.colour_columns.sort().join(), "Black,Red");

await cashier.goto(`${BASE}/quotes/waybills/${waybill.json.id}/preview`, { waitUntil: "networkidle" });
const waybillText = await cashier.locator("article.doc").innerText();
check("the waybill preview names the customer", waybillText.includes("Musa Traders"), true);
check("it shows no price", waybillText.includes("33,000"), false);
check("and no naira sign at all", waybillText.includes("₦"), false);

step("The quotation the customer receives");
await cashier.goto(`${BASE}/quotes/${quote.json.id}/preview`, { waitUntil: "networkidle" });
const quoteText = await cashier.locator("article.doc").innerText();
check("the quote preview shows the price", quoteText.includes("33,000"), true);
check("it names the customer", quoteText.includes("Musa Traders"), true);
check("it does not leak cost to the seller", quoteText.includes("Margin"), false);

const pdf = await call(cashier, `/api/quotes/${quote.json.id}/pdf/`);
check("the PDF renders", pdf.status, 200);

// ─────────────────────────────────────────────────────────────── 8. the owner adjusts access
step("The owner grants the employee permission to discount");
const member = staffAfter.find((m) => m.username === CASHIER);
const granted = await call(owner, `/api/staff/${member.id}/`, {
  method: "PATCH",
  body: JSON.stringify({ permissions: [...member.permissions, "discount"] }),
});
check("the permission is granted", granted.status, 200);

const discounted = await call(cashier, "/api/quotes/", {
  method: "POST",
  body: JSON.stringify({
    customer_name: "Musa Traders",
    staff_name: "Journey Cashier",
    line_items: [lineItem(28000)],
  }),
});
check("now they can discount", discounted.status, 201);
check(
  "and it is recorded against them",
  (await call(owner, "/api/activity/")).text.includes("instead of"),
  true,
);

step("Console");
check("no errors on the owner's screens", ownerErrors.length, 0);
check("no errors on the employee's screens", cashierErrors.length, 0);
if (ownerErrors.length) console.log(ownerErrors);
if (cashierErrors.length) console.log(cashierErrors);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nFull journey passed.");
