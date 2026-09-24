/**
 * The staff spine end to end: an owner sees their people, invites one, and the invited person
 * claims the link, sets a password and lands inside the business — restricted.
 *
 * This is the flow that makes Membership real. Everything else about staff access assumes a second
 * person can exist, and until this passes, none of them can.
 */
import { chromium } from "playwright";

import { BASE, launchOptions } from "./env.mjs";

const OWNER = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";
const NEW_STAFF = `cashier${Date.now().toString(36)}`;

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

async function call(page, url, options = {}) {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === "csrftoken")?.value;
  return page.evaluate(
    async ({ target, opts, csrf }) => {
      const r = await fetch(target, {
        ...opts,
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, ...(opts.headers || {}) },
        credentials: "include",
      });
      return { status: r.status, body: await r.text() };
    },
    { target: url, opts: options, csrf: token },
  );
}

const owner = await signIn(OWNER);

// --- the owner's view of their staff ---
const staff = await call(owner, "/api/staff/");
check("the owner can see the staff list", staff.status, 200);
check("the list already has people on it", JSON.parse(staff.body).length > 0, true);

const stores = JSON.parse((await call(owner, "/api/stores/")).body);
const ikeja = stores.find((s) => s.code === "IKJ");
check("the business has branches to assign", ikeja !== undefined, true);

// --- a role the business invented, not one the platform imposed ---
const cashier = await call(owner, "/api/roles/", {
  method: "POST",
  body: JSON.stringify({ name: `Cashier ${NEW_STAFF}`, permissions: ["catalogue", "quotes"] }),
});
check("the business can define its own role", cashier.status, 201);

// --- the invitation ---
const invite = await call(owner, "/api/invitations/", {
  method: "POST",
  body: JSON.stringify({
    email: `${NEW_STAFF}@example.com`,
    role_template: JSON.parse(cashier.body).id,
    stores: [ikeja.id],
  }),
});
check("the invitation is created", invite.status, 201);
const inviteUrl = JSON.parse(invite.body).invite_url;
check("it comes back with a one-time link", inviteUrl?.startsWith("/invite/"), true);

const listed = JSON.parse((await call(owner, "/api/invitations/")).body);
check("the link is not retrievable afterwards", listed[0].invite_url, null);
check("the invitation shows as pending", listed[0].status, "pending");

// --- the invited person claims it, with no account and no session ---
const token = inviteUrl.replace("/invite/", "");
const guest = await browser.newPage();
await guest.goto(`${BASE}/login`, { waitUntil: "networkidle" });
const accepted = await call(guest, "/api/auth/accept-invite/", {
  method: "POST",
  body: JSON.stringify({
    token,
    username: NEW_STAFF,
    password: "a-strong-pass-123",
    full_name: "New Cashier",
  }),
});
check("the invitation is accepted", accepted.status, 201);

// --- and they are inside the business, restricted ---
const theirQuotes = await call(guest, "/api/quotes/?page_size=50");
check("the new member can reach quotes", theirQuotes.status, 200);
check("they do not see cost", theirQuotes.body.includes("total_margin"), false);
check("they cannot reach purchases", (await call(guest, "/api/purchases/")).status, 403);
check("they cannot manage staff", (await call(guest, "/api/staff/")).status, 403);
check("another branch's quote is invisible", theirQuotes.body.includes("QT-ABA-1"), false);
check("their own branch's quote is visible", theirQuotes.body.includes("QT-IKJ-1"), true);

// --- the token is spent ---
const reuse = await call(guest, "/api/auth/accept-invite/", {
  method: "POST",
  body: JSON.stringify({ token, username: `${NEW_STAFF}b`, password: "a-strong-pass-123" }),
});
check("the link cannot be used twice", reuse.status, 400);

// --- and the owner now sees them ---
const after = JSON.parse((await call(owner, "/api/staff/")).body);
const added = after.find((m) => m.username === NEW_STAFF);
check("the new member appears on the staff list", added !== undefined, true);
check("scoped to the branch they were given", added?.store_names.join(), "Ikeja");

await browser.close();
if (failures.length) {
  console.log(`\n${failures.length} check(s) FAILED: ${failures.join(", ")}`);
  process.exit(1);
}
console.log("\nInvitation browser check passed.");
