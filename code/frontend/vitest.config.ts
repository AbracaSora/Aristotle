import { configDefaults, defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig({ command: "serve", mode: "test" }),
  defineConfig({
    test: {
      include: ["src/__tests__/**/*.{test,spec}.ts"],
      exclude: [...configDefaults.exclude, "tests/e2e/**"],
    },
  }),
);
