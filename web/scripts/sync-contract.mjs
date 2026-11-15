// Copies the machine-readable contract and the recorded fixtures into the web app.
//
//   docs/contract/presets.json  ->  web/src/generated/presets.json
//   cache/fixtures/<name>/      ->  web/public/fixtures/<name>/
//
// A recorded field's folder is mirrored whole: its manifest.json and frames.bin, and the recorded
// answers of the engine's routes when it has them (overlays.json, spectrum.json; both optional,
// read by src/api.ts loadRecordedOverlays and loadRecordedSpectrum). A file or a folder the source
// no longer has is removed from the copy.
//
// Runs before `dev`, `build` and `test` (see package.json). Both destinations are generated:
// never edit them by hand. Paths are resolved from this file, so the working directory is free.
import { copyFile, cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(webDir, "..");

const presetsSource = join(repoDir, "docs", "contract", "presets.json");
const presetsTarget = join(webDir, "src", "generated", "presets.json");
const fixturesSource = join(repoDir, "cache", "fixtures");
const fixturesTarget = join(webDir, "public", "fixtures");

/** Names of the visible sub-folders of `dir`; an absent folder counts as empty. */
async function listFolders(dir) {
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
}

/** Relative paths of every file below `dir`. */
async function listFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => relative(dir, join(entry.parentPath, entry.name)));
}

async function syncPresets() {
  await mkdir(dirname(presetsTarget), { recursive: true });
  await copyFile(presetsSource, presetsTarget);
}

/** Mirrors one fixture folder: overwrites in place, then drops files the source no longer has. */
async function mirrorFolder(source, target) {
  await cp(source, target, { recursive: true, force: true });
  const wanted = new Set(await listFiles(source));
  for (const file of await listFiles(target)) {
    if (!wanted.has(file)) await rm(join(target, file), { force: true });
  }
}

/** The recorded answers a fixture folder carries: "overlays", "spectrum", both or none. */
const RECORDED_ANSWERS = ["overlays", "spectrum"];

async function syncFixtures() {
  const names = await listFolders(fixturesSource);
  await mkdir(fixturesTarget, { recursive: true });
  for (const stale of await listFolders(fixturesTarget)) {
    if (!names.includes(stale)) {
      await rm(join(fixturesTarget, stale), { recursive: true, force: true });
    }
  }
  const copied = [];
  for (const name of names) {
    const target = join(fixturesTarget, name);
    await mirrorFolder(join(fixturesSource, name), target);
    const files = new Set(await listFiles(target));
    const answers = RECORDED_ANSWERS.filter((route) => files.has(`${route}.json`));
    copied.push(answers.length > 0 ? `${name} (recorded ${answers.join(" and ")})` : name);
  }
  return copied;
}

try {
  await syncPresets();
  const copied = await syncFixtures();
  const fixtures = copied.length > 0 ? copied.join(", ") : "none yet (cache/fixtures is empty)";
  console.log(`sync-contract: presets.json copied; fixtures: ${fixtures}`);
} catch (error) {
  const where = error.path ? relative(repoDir, error.path) : "";
  console.error(`sync-contract failed: ${error.code ?? error.message} ${where}`.trim());
  process.exitCode = 1;
}
