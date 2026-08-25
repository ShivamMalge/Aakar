import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["three"],
  // packages/scenespec sits outside apps/web, so the bundler needs to be told the
  // monorepo root is a legitimate source location for it.
  outputFileTracingRoot: resolve(dirname(fileURLToPath(import.meta.url)), "../.."),
};
export default nextConfig;
