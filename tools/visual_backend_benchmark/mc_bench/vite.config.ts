import { defineConfig } from "vite";
import motionCanvas from "@motion-canvas/vite-plugins";

export default defineConfig({
  plugins: [motionCanvas()],
});
