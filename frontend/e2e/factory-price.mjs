/**
 * The factory price column, end to end in a real browser.
 *
 * Signs in as the seeded owner, checks the catalogue toggle round-trips, builds a quote and
 * confirms the customer-facing preview shows the manufacturer's price and the saving — and, most
 * importantly, never shows what the distributor paid.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const USERNAME = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (m) => {
  if (m.type() !== "error") return;
  // The refused PATCH below is deliberate, so its network error is expected noise.
  if (m.text().includes("400 (Bad Request)")) return;
  consoleErrors.push(m.text());
});

await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.locator('input[autocomplete="username"]').fill(USERNAME);
await page.locator('input[type="password"]').fill(PASSWORD);
await page.locator('button[type="submit"]').click();
await page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 });

// Set up the state this test needs rather than assuming a stack has it: a seeded database has
// the toggle off and no factory prices, so depending on them would fail in CI for the wrong reason.
await page.goto(`${BASE}/catalogue`, { waitUntil: "networkidle" });
const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value;

const size = await page.evaluate(async (token) => {
  await fetch("/api/profile/", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    credentials: "include",
    body: JSON.stringify({ show_factory_price: true }),
  });
  const types = await (await fetch("/api/cable-types/", { credentials: "include" })).json();
  const first = types.flatMap((t) => t.sizes)[0];
  const factory = (Number(first.default_price) * 1.2).toFixed(2);
  const r = await fetch(`/api/sizes/${first.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    credentials: "include",
    body: JSON.stringify({ factory_price: factory }),
  });
  return r.ok ? r.json() : null;
}, csrf);
check("a factory price can be set on a catalogue item", size !== null, true);

// --- The toggle on the catalogue reflects what was saved ---
await page.reload({ waitUntil: "networkidle" });
const toggle = page.locator(".factory-toggle input");
check("the catalogue carries the toggle", await toggle.count(), 1);
check("the toggle reflects the saved preference", await toggle.isChecked(), true);

const refused = await page.evaluate(
  async ({ id, token, price }) => {
    const r = await fetch(`/api/sizes/${id}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      credentials: "include",
      body: JSON.stringify({ factory_price: price }),
    });
    return { status: r.status, body: JSON.stringify(await r.json()) };
  },
  { id: size.id, token: csrf, price: "1.00" },
);
check("a factory price below the sale price is refused", refused.status, 400);
check("the refusal says it is not the purchase cost", refused.body.includes("not what you paid"), true);

// --- A quote shows the comparison ---
const quote = await page.evaluate(
  async ({ token, sizeId }) => {
    const r = await fetch("/api/quotes/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      credentials: "include",
      body: JSON.stringify({
        customer_name: "Browser Check",
        staff_name: "Ada",
        line_items: [
          {
            kind: "cable",
            cable_size: sizeId,
            cable_type_name: "Singles",
            size_label: "x",
            unit: "coil",
            unit_price: "1000.00",
            colours: [{ colour: "", quantity: 2 }],
          },
        ],
      }),
    });
    return { status: r.status, body: await r.json() };
  },
  { token: csrf, sizeId: size.id },
);
check("the quote saved", quote.status, 201);
check("the line snapshotted the factory price", quote.body.line_items[0].factory_price, size.factory_price);
check("the quote inherited the toggle", quote.body.show_factory_price, true);

// --- The customer-facing preview ---
await page.goto(`${BASE}/quotes/${quote.body.id}/preview`, { waitUntil: "networkidle" });
const table = await page.locator(".doc-table, table").first().innerText();
check("the preview shows a Factory column", table.includes("Factory"), true);
check("the preview shows the saving", (await page.locator(".quote-saving").count()) > 0, true);

// The failure this feature could cause: printing what the distributor paid.
const body = await page.locator("body").innerText();
const cost = quote.body.line_items[0].unit_cost;
check("cost is not rendered on the customer preview", cost === null || !body.includes(String(cost)), true);

check("no console errors", consoleErrors.length, 0);
if (consoleErrors.length) console.log(consoleErrors);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nFactory price browser check passed.");
