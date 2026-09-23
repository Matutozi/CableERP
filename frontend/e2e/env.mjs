/**
 * Shared environment for the browser tests.
 *
 * BASE defaults to `localhost`, never `127.0.0.1`. CI starts Vite with no `--host`, so it binds to
 * `localhost` only — and Node 17+ resolves that to ::1 before 127.0.0.1. Connecting to the literal
 * IPv4 address is then refused even though the server is up. Both tests import from here so they
 * cannot disagree about it again.
 */
export const BASE = process.env.BASE_URL ?? "http://localhost:5173";

export const launchOptions = {
  executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
  args: ["--no-sandbox"],
};
