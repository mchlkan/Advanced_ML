// Run: npm install --no-save sharp && node scripts/gen-icons.mjs

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import sharp from "sharp";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PUBLIC = resolve(__dirname, "..", "public");

// librsvg (sharp's SVG backend) doesn't parse oklch(); substitute the sRGB
// equivalent of oklch(0.62 0.15 145) before render.
const ACCENT_HEX = "#3aa564";

async function loadSvg(name) {
  const raw = await readFile(resolve(PUBLIC, name), "utf8");
  return Buffer.from(raw.replaceAll("oklch(0.62 0.15 145)", ACCENT_HEX));
}

async function render(svgBuf, size, outName) {
  await sharp(svgBuf, { density: 384 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toFile(resolve(PUBLIC, outName));
  console.log(`wrote ${outName} (${size}x${size})`);
}

const main = await loadSvg("icon.svg");
const maskable = await loadSvg("icon-maskable.svg");

await render(main, 192, "icon-192.png");
await render(main, 512, "icon-512.png");
await render(maskable, 512, "icon-512-maskable.png");
await render(main, 180, "apple-touch-icon.png");
await render(main, 32, "favicon-32.png");

// sharp can't write .ico; modern browsers accept PNG-as-favicon.
const fav32 = await sharp(main, { density: 384 })
  .resize(32, 32)
  .png({ compressionLevel: 9 })
  .toBuffer();
await writeFile(resolve(PUBLIC, "favicon.ico"), fav32);
console.log("wrote favicon.ico (32x32 PNG-in-ICO)");
