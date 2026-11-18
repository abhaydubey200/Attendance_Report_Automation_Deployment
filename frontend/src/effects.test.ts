// Guard: a React effect must return nothing or a cleanup function. An arrow effect without braces returns whatever
// its expression returns - e.g. newer Chromium returns a Promise from smooth scrollIntoView, which blanked the app
// when HR left the Employees page after opening Edit. Only plain state setters are allowed in that short form.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(n) && !n.includes(".test.") ? [p] : [];
  });
}

test("effects never return a value (only braces or a state setter)", () => {
  const bad: string[] = [];
  for (const f of files(join(__dirname))) {
    for (const m of readFileSync(f, "utf8").matchAll(/use(?:Layout)?Effect\(\(\)\s*=>\s*([^{\s][^\n]*)/g)) {
      if (!/^set[A-Z]\w*\(/.test(m[1])) bad.push(`${f}: ${m[0].slice(0, 90)}`);
    }
  }
  expect(bad).toEqual([]);
});
