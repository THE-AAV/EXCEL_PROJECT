import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the backend runs on :8000 (uvicorn server.main:create_app --factory --reload).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: {
    chunkSizeWarningLimit: 1500,
    rollupOptions: { output: { manualChunks: { grid: ["ag-grid-community", "ag-grid-react"] } } },
  },
});
