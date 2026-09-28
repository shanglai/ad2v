// Shared test fixture: the demo .ad2v (built by scripts/make_fixtures.py) through LocalFileSource.
import fs from "node:fs";
import path from "node:path";
import { LocalFileSource } from "../src/data/LocalFileSource";

export const FIXTURES = path.join(__dirname, "fixtures");
let cached: Promise<LocalFileSource> | null = null;

export function source(): Promise<LocalFileSource> {
  cached ??= LocalFileSource.fromBytes(new Uint8Array(fs.readFileSync(path.join(FIXTURES, "demo.ad2v"))));
  return cached;
}

export function json<T>(name: string): T {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf8")) as T;
}
