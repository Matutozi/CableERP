/**
 * End-to-end smoke test: sign in, build a quote, check the figures the customer would see, download the PDF.
 *
 *   npm run e2e                     # against a seeded stack on http://localhost:5173
 *
 * Env: BASE_URL, E2E_USERNAME, E2E_PASSWORD, CHROMIUM_EXECUTABLE (to reuse an already-installed browser).
 * This is the test that caught a price field appending digits — it is worth keeping in CI.
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:5173";
const USERNAME = process.env.E2E_USERNAME ?? "acmeoaks";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-pass-123";

const failures = [];
const problems = [];
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}: ${actual}${ok ? "" : ` (expected ${expected})`}`);
  if (!ok) failures.push(label);
}

const money = (text) => Number(text.replace(/[^\d.]/g, ""));
const naira = (value) => `₦${value.toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
  args: ["--no-sandbox"],
});
const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })).newPage();
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
page.on("console", (message) => message.type() === "error" && problems.push(`console: ${message.text()}`));

try {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Username").fill(USERNAME);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "New quote" }).waitFor();

  await page.goto(`${BASE}/quotes/new`);
  await page.getByPlaceholder("Customer name").fill("Smoke test customer");
  // Find the pickers by their accessible names, not placeholder text: the placeholders were
  // reworded when these became dropdowns, and that silently broke this test.
  await page.getByRole("combobox", { name: "Cable type" }).first().fill("Singles");
  await page.keyboard.press("Escape"); // close the list so it can't cover the next field on a phone
  await page.getByRole("combobox", { name: "Size" }).first().fill("1.5mm");
  await page.keyboard.press("Escape");
  await page.getByLabel("Red quantity").fill("30");

  // The price comes from the catalogue, so work the expectation out from what the screen shows.
  const unitPrice = money(await page.getByLabel("Unit price").first().inputValue());
  const vat = money(await page.getByLabel("VAT percentage").inputValue());
  const expected = Math.round(unitPrice * 30 * (1 + vat / 100) * 100) / 100;
  check("line amount", await page.locator(".item-total").first().innerText(), naira(unitPrice * 30));
  check("grand total in the editor", await page.locator(".grand strong").innerText(), naira(expected));

  await page.getByRole("button", { name: "Generate PDF" }).click();
  await page.waitForURL(/\/quotes\/\d+\/preview$/);
  await page.getByText("QUOTATION", { exact: true }).waitFor();
  check("grand total the server printed", await page.locator(".doc-grand span").last().innerText(), naira(expected));

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download" }).click(),
  ]);
  check("PDF filename", /^QT-\d{8}-\d{3}\.pdf$/.test(download.suggestedFilename()), true);
} catch (error) {
  failures.push(`threw: ${error.message.split("\n")[0]}`);
  console.error(error);
} finally {
  await browser.close();
}

if (problems.length) {
  console.log(`\nBrowser problems:\n${problems.join("\n")}`);
  failures.push("console or page errors");
}
console.log(failures.length ? `\nFAILED: ${failures.join(", ")}` : "\nSmoke test passed.");
process.exit(failures.length ? 1 : 0);
