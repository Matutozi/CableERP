/**
 * Browser check for the membership spine: register a business through the real UI and confirm
 * the app lets the new owner straight in. The DB assertions run separately, after this.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

// Unique per run: re-running against a database that already has this user would otherwise fail
// at registration and surface only as a navigation timeout.
const USER = process.env.NEW_USER ?? `browsertest${Date.now().toString(36)}`;
const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

await page.goto(`${BASE}/register`, { waitUntil: "networkidle" });
// Attribute selectors, not label proximity: the Field component renders every input under one
// parent, so an xpath ".." from a label matches the whole form.
await page.locator('input[placeholder*="Acme-Oaks"]').fill("Browser Test Cables");
await page.locator('input[autocomplete="username"]').fill(USER);
await page.locator('input[type="password"]').fill("a-strong-pass-123");
await page.locator('button[type="submit"]').click();

// Registration signs the user in and lands them on the dashboard.
try {
  await page.waitForURL((u) => !u.pathname.includes("register"), { timeout: 15000 });
} catch {
  // The timeout itself says nothing useful; the page's own error message does.
  const message = await page.locator(".alert-error, .field-error").allInnerTexts();
  console.log(`FAIL registration did not complete: ${message.join(" | ") || "no error shown on the page"}`);
  await browser.close();
  process.exit(1);
}
check("left the register page", !page.url().includes("register"), true);

// The profile call is the one that carries the new allowance fields.
const profile = await page.evaluate(async () => {
  const r = await fetch("/api/profile/", { credentials: "include" });
  return r.ok ? r.json() : { error: r.status };
});
check("store_limit in payload", profile.store_limit, 1);
check("active_store_count in payload", profile.active_store_count, 1);
check("is_over_store_limit in payload", profile.is_over_store_limit, false);

// Q21: the allowance must not be writable, even by the owner, even straight at the API.
const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value;
const attempt = await page.evaluate(async (token) => {
  const r = await fetch("/api/profile/", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    credentials: "include",
    body: JSON.stringify({ store_limit: 99 }),
  });
  return { status: r.status, body: await r.json() };
}, csrf);
check("PATCH accepted (field ignored, not rejected)", attempt.status, 200);
check("store_limit unchanged after PATCH", attempt.body.store_limit, 1);

check("no console errors", errors.length, 0);
if (errors.length) console.log(errors);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nSpine browser check passed.");
