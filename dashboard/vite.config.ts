import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go straight into the backend so FastAPI serves them at /admin
export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: {
    outDir: "../backend/app/static/admin",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/admin/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
