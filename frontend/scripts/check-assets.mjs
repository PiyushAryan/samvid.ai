import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

const root = process.cwd();
const publicRoot = join(root, "public");
const referenceRoots = [join(root, "src"), join(root, "scripts")];
const referenceExtensions = new Set([".css", ".js", ".json", ".mjs", ".ts", ".tsx"]);

function walk(directory) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const source = referenceRoots
  .flatMap(walk)
  .filter((path) => referenceExtensions.has(extname(path)))
  .map((path) => readFileSync(path, "utf8"))
  .join("\n");

const failures = walk(publicRoot)
  .filter((path) => !path.endsWith(".DS_Store"))
  .filter((path) => !source.includes(`/${relative(publicRoot, path).replaceAll("\\", "/")}`))
  .map((path) => `unreferenced public asset: public/${relative(publicRoot, path)}`);

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("Public assets are referenced.");
