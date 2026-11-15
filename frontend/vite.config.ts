import { defineConfig } from "vite";
// During development this is the local end of an SSH forward to the edge service.
export default defineConfig({
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:18081", ws: true },
      "/healthz": { target: "http://127.0.0.1:18081" },
    },
  },
});
