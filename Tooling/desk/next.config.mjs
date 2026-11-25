/** @type {import('next').NextConfig} */
const nextConfig = {
  // @libsql/client is a native module: it has to be required at runtime from
  // node_modules rather than traced into the bundle.
  serverExternalPackages: ["@libsql/client", "libsql"],
};
export default nextConfig;
