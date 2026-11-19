// Salin decoder zxing (.wasm) ke public/ agar scan kamera tidak bergantung CDN pihak ketiga.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
// zxing-wasm adalah dependency dari barcode-detector -> resolve dari lokasi paket itu.
const detectorEntry = require.resolve("barcode-detector/ponyfill");
const wasm = createRequire(detectorEntry).resolve("zxing-wasm/reader/zxing_reader.wasm");
const out = resolve(here, "..", "public", "zxing");
mkdirSync(out, { recursive: true });
copyFileSync(wasm, join(out, "zxing_reader.wasm"));
console.log("zxing_reader.wasm -> public/zxing/");
