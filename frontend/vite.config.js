import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Django runs on :8000. Proxying keeps the API on the same origin as the app,
// so Django's session and CSRF cookies work without any CORS setup.
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/media": backend,
    },
  },
});
