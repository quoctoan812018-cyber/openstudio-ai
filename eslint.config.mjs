import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["**/.venv/**", "**/dist/**", "apps/daemon/**", "templates/**", "**/node_modules/**", "**/.runtime/**", "OpenCreator-master/**", "reference/**", "apps/desktop/build/**", "packages/protocol/src/generated/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["apps/web/src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["apps/desktop/**/*.cjs", "scripts/**/*.mjs", "*.mjs"],
    languageOptions: { globals: { ...globals.node }, sourceType: "commonjs" },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  { files: ["scripts/**/*.mjs", "*.mjs"], languageOptions: { sourceType: "module" } },
);
