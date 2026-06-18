import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: the React app calls `/api/*` (same-origin), and Vite forwards to the
// uvicorn backend on :8000, stripping the `/api` prefix. So `GET /api/review/...`
// → `GET http://localhost:8000/review/...`. SAP stays off; the backend is the mock seam.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
