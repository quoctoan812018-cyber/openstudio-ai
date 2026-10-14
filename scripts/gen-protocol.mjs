// Pydantic → JSON Schema → TypeScript (packages/protocol/src/index.ts)
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const schemaPath = join(root, "packages/protocol/schema.json");

const py = spawnSync("uv", ["run", "--project", "apps/daemon", "python", "-m", "openstudio.protocol_gen", schemaPath], {
  cwd: root, stdio: "inherit", env: { ...process.env, PYTHONPATH: join(root, "apps/daemon") }, shell: process.platform === "win32",
});
if (py.status !== 0) process.exit(py.status ?? 1);

const require = createRequire(join(root, "packages/protocol/package.json"));
const { compile } = require("json-schema-to-typescript");
const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
const ts = await compile(schema, "OpenStudioProtocol", {
  bannerComment: "/* AUTO-GENERATED từ Pydantic (pnpm protocol:gen). KHÔNG sửa tay. */",
  additionalProperties: false,
  declareExternallyReferenced: true,
  unreachableDefinitions: true,
});
mkdirSync(join(root, "packages/protocol/src"), { recursive: true });
writeFileSync(join(root, "packages/protocol/src/index.ts"), ts);
console.log("wrote packages/protocol/src/index.ts");
