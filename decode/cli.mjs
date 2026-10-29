// Command line wrapper around tcstring.mjs, used by decoder.py: one TC string per input line,
// one JSON object per output line, in the same order. Decoding many strings in one Node process
// avoids starting Node for every string.
//
//   printf '%s\n' CPx... CQy... | node decode/cli.mjs

import { createInterface } from "node:readline";
import { decodeTCString } from "./tcstring.mjs";

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  const tcString = line.trim();
  process.stdout.write(JSON.stringify({ tcString, ...decodeTCString(tcString) }) + "\n");
}
