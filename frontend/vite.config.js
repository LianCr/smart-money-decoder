import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 默认端口 5173，已在后端 CORS 白名单内
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
