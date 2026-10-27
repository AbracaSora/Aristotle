import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.ARISTOTLE_BACKEND_URL || "http://127.0.0.1:8018";
  const proxy = {
    "/api": { target, changeOrigin: true },
    "/backend-demo": {
      target,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/backend-demo/, "/demo"),
    },
  };
  return {
    plugins: [vue()],
    server: { port: 5173, host: "localhost", proxy },
    preview: { proxy },
  };
});
