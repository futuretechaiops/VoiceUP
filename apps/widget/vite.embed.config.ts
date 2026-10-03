import { defineConfig } from "vite";

// Builds the single-file script customers embed: dist-embed/widget.js
export default defineConfig({
  build: {
    outDir: "dist-embed",
    emptyOutDir: true,
    lib: { entry: "src/index.ts", name: "AiSalesConcierge", formats: ["iife"], fileName: () => "widget.js" },
    minify: true,
  },
});
