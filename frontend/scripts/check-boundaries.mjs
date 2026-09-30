import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, extname, join, relative, resolve, sep } from "node:path";
import ts from "typescript";

const sourceRoot = join(process.cwd(), "src");
const legacyModules = new Set([
  "Admin.tsx",
  "App.tsx",
  "AuthPage.tsx",
  "AuthProvider.tsx",
  "AuthRoute.tsx",
  "Home.tsx",
  "Integrations.tsx",
  "Settings.tsx",
  "api.ts",
  "types.ts"
]);

function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

function featureName(path) {
  const marker = `${sep}features${sep}`;
  const index = path.indexOf(marker);
  if (index < 0) return null;
  return path.slice(index + marker.length).split(sep)[0] || null;
}

function moduleSpecifiers(file, source) {
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, extname(file) === ".tsx" ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const values = [];
  const visit = (node) => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      values.push(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
      values.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return values;
}

function resolvedModule(file, specifier) {
  if (specifier.startsWith("@/")) return join(sourceRoot, specifier.slice(2));
  if (specifier.startsWith(".")) return resolve(dirname(file), specifier);
  return null;
}

function isPageOrShellImport(path) {
  const name = basename(path).replace(/\.(?:tsx?|jsx?)$/, "");
  return name === "page" || name.endsWith("-page") || name === "app-shell" || name === "admin-shell";
}

const failures = [];
for (const legacy of legacyModules) {
  if (existsSync(join(sourceRoot, legacy))) failures.push(`legacy root module still exists: src/${legacy}`);
}
for (const forbidden of ["workspace-app.tsx", "admin.tsx", "api-client.ts", "domain-types.ts"]) {
  for (const file of walk(sourceRoot)) {
    if (basename(file) === forbidden) failures.push(`legacy monolith or facade still exists: src/${relative(sourceRoot, file)}`);
  }
}

for (const file of walk(sourceRoot).filter((path) => /\.[jt]sx?$/.test(path))) {
  const rel = relative(sourceRoot, file);
  const isTest = /\.test\.[jt]sx?$/.test(file);
  const imports = moduleSpecifiers(file, readFileSync(file, "utf8"));

  for (const specifier of imports) {
    const target = resolvedModule(file, specifier);
    if (!target) continue;

    if (/^app(?:\/|\\).+page\.tsx$/.test(rel.replaceAll(sep, "/")) && specifier.startsWith("@/") && !specifier.startsWith("@/features/")) {
      failures.push(`route page must import a feature entrypoint: src/${rel} -> ${specifier}`);
    }

    if ((rel.startsWith(`lib${sep}`) || rel.startsWith(`components${sep}ui${sep}`) || rel.startsWith(`components${sep}shared${sep}`)) && specifier.startsWith("@/features/")) {
      failures.push(`shared layer imports a feature: src/${rel} -> ${specifier}`);
    }

    if (!isTest) {
      const sourceFeature = featureName(file);
      const targetFeature = featureName(target);
      if (sourceFeature && targetFeature && sourceFeature !== targetFeature && isPageOrShellImport(target)) {
        failures.push(`feature imports another feature page or shell: src/${rel} -> ${specifier}`);
      }
    }
  }
}

if (failures.length) {
  console.error([...new Set(failures)].join("\n"));
  process.exit(1);
}

console.log("Frontend import boundaries are clean.");
