/**
 * The waybill preview: the driver's copy, on screen.
 *
 * The check that matters is the last one. A waybill travels with the goods and is read by a driver,
 * a gateman and whoever signs for the delivery — so no price may appear on it, and this asserts
 * that against the rendered page rather than trusting the template.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";
const UNIT_PRICE = "33000";

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));

await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.locator('input[autocomplete="username"]').fill(OWNER);
await page.locator('input[type="password"]').fill(PASSWORD);
await page.locator('button[type="submit"]').click();
await page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 });

async function call(url, options = {}) {
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

// Build the quote this waybill comes from, so the test does not depend on seeded documents.
const quote = await call("/api/quotes/", {
  method: "POST",
  body: JSON.stringify({
    customer_name: "Driver Test Ltd",
    staff_name: "Ada",
    line_items: [
      {
        cable_type_name: "Singles",
        size_label: "1.5mm",
        unit: "coil",
        unit_price: UNIT_PRICE,
        colours: [{ colour: "Red", quantity: 3 }],
      },
    ],
  }),
});
check("a quote was created to build from", quote.status, 201);

const waybill = await call("/api/waybills/", {
  method: "POST",
  body: JSON.stringify({ quote: JSON.parse(quote.body).id }),
});
check("a waybill was created from it", waybill.status, 201);
const created = JSON.parse(waybill.body);

// --- the list offers a way in ---
await page.goto(`${BASE}/quotes/waybills`, { waitUntil: "networkidle" });
const previewLink = page.locator(`a[href="/quotes/waybills/${created.id}/preview"]`);
check("the waybill list has a Preview button", await previewLink.count(), 1);

await previewLink.first().click();
await page.waitForURL((u) => u.pathname.endsWith("/preview"), { timeout: 15000 });

// --- the preview itself ---
const body = await page.locator("article.doc").innerText();
check("the page is titled WAYBILL", body.includes("WAYBILL"), true);
check("it names the customer", body.includes("Driver Test Ltd"), true);
check("it carries the waybill reference", body.includes(created.reference_number), true);
check("it shows the quantity", body.includes("3"), true);
check("it has somewhere to sign", (await page.locator(".doc-sign-line").count()) >= 2, true);
check("Download PDF is offered", await page.getByRole("button", { name: /download pdf/i }).count(), 1);

// The whole point of the document.
check("no unit price anywhere on the page", body.includes("33,000"), false);
check("no naira sign anywhere on the page", body.includes("₦"), false);

check("no console errors", consoleErrors.length, 0);
if (consoleErrors.length) console.log(consoleErrors);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nWaybill preview browser check passed.");
