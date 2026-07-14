import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // set-state-in-effect flags legitimate "sync prop to state" patterns
      // in form components where local state mirrors server-loaded data.
      // These are not cascading — they set once when the prop value arrives.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
]);

export default eslintConfig;
