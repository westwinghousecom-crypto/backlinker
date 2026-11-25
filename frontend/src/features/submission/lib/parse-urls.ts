/** Split on newlines, strip all whitespace, drop empties, dedupe (order kept). */
export function parseUrls(raw: string): string[] {
  const seen = new Set<string>();
  for (const line of raw.split(/\r?\n/)) {
    const url = line.replace(/\s+/g, "");
    if (url) seen.add(url);
  }
  return [...seen];
}
