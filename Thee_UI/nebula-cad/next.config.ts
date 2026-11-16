import type { NextConfig } from "next";

// cacheComponents / partialPrefetching (create-next-app defaults) are off on purpose:
// every screen is client-rendered against the adapter layer, so there is no server
// data to cache. See docs/ARCHITECTURE.md, decision D14.
const nextConfig: NextConfig = {
  devIndicators: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
