import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const sourceRoot = join(process.cwd(), "src");
const legacyRoots = [
  "App.tsx",
  "Admin.tsx",
  "AuthPage.tsx",
  "AuthProvider.tsx",
  "AuthRoute.tsx",
  "Home.tsx",
  "Settings.tsx",
  "Integrations.tsx",
  "api.ts",
  "types.ts"
];
const legacyImport = /(?:from\s+["'](?:\.{1,2}\/)*(?:App|Admin|AuthPage|AuthProvider|AuthRoute|Home|Settings|Integrations|api|types)["']|from\s+["']@\/(?:App|Admin|AuthPage|AuthProvider|AuthRoute|Home|Settings|Integrations|api|types)["'])/;

function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const failures = legacyRoots
  .filter((file) => existsSync(join(sourceRoot, file)))
  .map((file) => `legacy root module still exists: src/${file}`);

for (const file of walk(sourceRoot).filter((path) => /\.[jt]sx?$/.test(path))) {
  const source = readFileSync(file, "utf8");
  if (legacyImport.test(source)) {
    failures.push(`legacy root import: src/${relative(sourceRoot, file)}`);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("Frontend boundaries are clean.");
