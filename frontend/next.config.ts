import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Use the compiler API: this environment returns empty captured CLI config output.
  // Type checking remains enabled; standalone tsc is also part of validation.
  experimental: { useTypeScriptCli: false },
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
