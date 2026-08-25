import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // لا نحتاج توليد AGENTS.md و CLAUDE.md تلقائيًا داخل frontend/.
  agentRules: false,
};

export default nextConfig;
