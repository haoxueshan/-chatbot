import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  // Only read frontend host configuration; never load server API credentials.
  const env = loadEnv(mode, process.cwd(), "CLASSBRIDGE_");
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 80,
      strictPort: true,
      allowedHosts: (env.CLASSBRIDGE_ALLOWED_HOSTS || "")
        .split(",")
        .map((host) => host.trim())
        .filter(Boolean),
      proxy: {
        "/api": { target: "http://127.0.0.1:8000" },
        "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      },
    },
  };
});
