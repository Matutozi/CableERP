/**
 * The staff screens, driven the way an owner would: click Invite, fill the form, copy the link,
 * open it in a fresh browser context with no session, and join.
 *
 * The API-level flow is covered by invitations.mjs. This covers the half that is easy to get wrong
 * and impossible to unit test — whether a person can actually complete it in the app.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";
const NEW_STAFF = `uistaff${Date.now().toString(36)}`;

const failures = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const browser = await chromium.launch(launchOptions);
const owner = await browser.newPage();
const consoleErrors = [];
owner.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));

await owner.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await owner.locator('input[autocomplete="username"]').fill(OWNER);
await owner.locator('input[type="password"]').fill(PASSWORD);
await owner.locator('button[type="submit"]').click();
await owner.waitForURL((u) => !u.pathname.includes("login"), { timeout: 15000 });

// --- the staff page exists and is reachable from the nav ---
await owner.goto(`${BASE}/staff`, { waitUntil: "networkidle" });
check("the staff page lists people", (await owner.locator(".member").count()) > 0, true);
check("the owner is tagged as such", (await owner.locator(".tag", { hasText: "Owner" }).count()) > 0, true);

// --- inviting someone ---
await owner.getByRole("button", { name: /invite someone/i }).click();
check("the invite form opens", await owner.locator(".invite-form").count(), 1);

const permissionCount = await owner.locator(".invite-form .permission-option input").count();
check("permissions are tickable per person", permissionCount > 5, true);

await owner.locator('.invite-form input[placeholder="08030000000"]').fill(`${NEW_STAFF}@example.com`);
await owner.locator('.invite-form input[placeholder="Emeka Obi"]').fill("UI Test Staff");
await owner.locator(".invite-form select").selectOption({ label: "Sales" });
await owner.getByRole("button", { name: /create invite link/i }).click();

await owner.locator(".invite-link").waitFor({ timeout: 15000 });
const url = await owner.locator(".invite-url").inputValue();
check("a one-time link is shown", url.includes("/invite/"), true);
check(
  "the page warns it cannot be shown again",
  (await owner.locator(".invite-link").innerText()).includes("cannot be shown again"),
  true,
);

await owner.getByRole("button", { name: /^done$/i }).click();
check(
  "the invite now shows as waiting",
  (await owner.locator(".page").innerText()).includes("Waiting to join"),
  true,
);

// --- the invited person, with no account and no session ---
const guest = await browser.newContext();
const guestPage = await guest.newPage();
await guestPage.goto(url.replace(/^https?:\/\/[^/]+/, BASE), { waitUntil: "networkidle" });
check("the invite page loads signed out", (await guestPage.locator("h1").innerText()).includes("Join"), true);

await guestPage.locator('input[autocomplete="name"]').fill("UI Test Staff");
await guestPage.locator('input[autocomplete="username"]').fill(NEW_STAFF);
await guestPage.locator('input[autocomplete="new-password"]').fill("a-strong-pass-123");
await guestPage.getByRole("button", { name: /^join$/i }).click();

await guestPage.waitForURL((u) => !u.pathname.includes("invite"), { timeout: 15000 });
check("joining signs them straight in", !guestPage.url().includes("/invite/"), true);

// --- and they arrive restricted ---
const theirs = await guestPage.evaluate(async () => {
  const r = await fetch("/api/purchases/", { credentials: "include" });
  return r.status;
});
check("the new member cannot reach purchases", theirs, 403);

// --- a spent link says so rather than failing silently ---
const second = await guest.newPage();
await second.goto(url.replace(/^https?:\/\/[^/]+/, BASE), { waitUntil: "networkidle" });
await second.locator('input[autocomplete="username"]').fill(`${NEW_STAFF}x`);
await second.locator('input[autocomplete="new-password"]').fill("a-strong-pass-123");
await second.getByRole("button", { name: /^join$/i }).click();
await second.locator(".alert-error").waitFor({ timeout: 15000 });
check("a spent link explains itself", (await second.locator(".alert-error").innerText()).length > 0, true);

// --- the owner sees the new person ---
await owner.reload({ waitUntil: "networkidle" });
check(
  "the new member appears on the staff list",
  (await owner.locator(".page").innerText()).includes("UI Test Staff"),
  true,
);

check("no console errors", consoleErrors.length, 0);
if (consoleErrors.length) console.log(consoleErrors);

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nStaff UI browser check passed.");
