import type { ReactNode } from "react";

/** A deliberately tiny markdown subset for our own legal drafts: #/## headings, paragraphs, - lists, tables, **bold**,
 *  `code`, [links](url) and [PLACEHOLDERS] (shown highlighted so nobody publishes them by accident). */
export type Block =
  | { type: "h1" | "h2"; text: string }
  | { type: "p"; lines: string[] }
  | { type: "ul"; items: string[] }
  | { type: "table"; header: string[]; rows: string[][] };

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());

export function parseMarkdown(md: string): Block[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
    } else if (line.startsWith("## ")) {
      blocks.push({ type: "h2", text: line.slice(3).trim() });
      i++;
    } else if (line.startsWith("# ")) {
      blocks.push({ type: "h1", text: line.slice(2).trim() });
      i++;
    } else if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2).trim());
      blocks.push({ type: "ul", items });
    } else if (line.trimStart().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trimStart().startsWith("|")) rows.push(cells(lines[i++]));
      const [header, , ...body] = rows; // second row is the --- separator
      blocks.push({ type: "table", header, rows: body });
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,2} |- |\|)/.test(lines[i])) para.push(lines[i++].trim());
      blocks.push({ type: "p", lines: para });
    }
  }
  return blocks;
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\[[^\]]+\])/g;
const SAFE_HREF = /^(https?:\/\/|\/)/;

export function renderInline(text: string): ReactNode[] {
  return text.split(TOKEN).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`"))
      return (
        <code key={i} className="rounded bg-slate-800 px-1 py-0.5 text-[0.9em]">
          {part.slice(1, -1)}
        </code>
      );
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      if (!SAFE_HREF.test(href)) return <span key={i}>{label}</span>;
      const external = href.startsWith("http");
      return (
        <a
          key={i}
          href={href}
          className="text-emerald-400 underline underline-offset-2"
          {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
        >
          {label}
        </a>
      );
    }
    if (/^\[[^\]]+\]$/.test(part))
      return (
        <mark key={i} className="rounded bg-amber-900/60 px-1 text-amber-200" data-placeholder>
          {part}
        </mark>
      );
    return part;
  });
}

export function Markdown({ source }: { source: string }) {
  return (
    <div className="space-y-3 text-sm leading-relaxed text-slate-300">
      {parseMarkdown(source).map((b, i) => {
        switch (b.type) {
          case "h1":
            return (
              <h1 key={i} className="text-2xl font-semibold text-slate-100">
                {renderInline(b.text)}
              </h1>
            );
          case "h2":
            return (
              <h2 key={i} className="pt-3 text-lg font-semibold text-slate-100">
                {renderInline(b.text)}
              </h2>
            );
          case "ul":
            return (
              <ul key={i} className="list-disc space-y-1 pl-5">
                {b.items.map((it, j) => (
                  <li key={j}>{renderInline(it)}</li>
                ))}
              </ul>
            );
          case "table":
            return (
              <div key={i} className="overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr>
                      {b.header.map((h, j) => (
                        <th key={j} className="border-b border-slate-700 px-2 py-1 font-medium text-slate-200">
                          {renderInline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>
                        {r.map((c, k) => (
                          <td key={k} className="border-b border-slate-800 px-2 py-1 align-top">
                            {renderInline(c)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return (
              <p key={i}>
                {b.lines.map((l, j) => (
                  <span key={j}>
                    {j > 0 && <br />}
                    {renderInline(l)}
                  </span>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
