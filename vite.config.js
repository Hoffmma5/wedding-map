import { defineConfig } from "vite";

export default defineConfig({
  base: "./",          // relative asset paths, so the build can be hosted in any sub-folder
  build: { target: "es2022", chunkSizeWarningLimit: 4000 },
});
