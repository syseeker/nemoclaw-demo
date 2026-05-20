import { useMemo, useState, type ReactElement } from "react";

type PlannerStatus = {
  state: string;
  message: string;
} | null;

interface PlannerPanelProps {
  status: PlannerStatus;
  markdown: string;
}

export function PlannerPanel({ status, markdown }: PlannerPanelProps) {
  const [expanded, setExpanded] = useState<boolean>(false);
  const isWorking = status?.state === "working";
  const statusClass = isWorking
    ? "bg-amber-100 text-amber-800 border-amber-200"
    : status?.state === "done"
      ? "bg-emerald-100 text-emerald-800 border-emerald-200"
      : "bg-slate-100 text-slate-700 border-slate-200";
  const rendered = useMemo(() => renderMarkdownLite(markdown), [markdown]);

  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Planner</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-700 hover:bg-gray-50"
            onClick={() => setExpanded((curr) => !curr)}
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
          <div className={`rounded-full border px-2 py-0.5 text-xs ${statusClass}`}>
            {isWorking ? "● " : ""}{status?.message || "Idle"}
          </div>
        </div>
      </div>
      <div className={`${expanded ? "max-h-[52vh]" : "max-h-40"} overflow-y-auto text-sm text-gray-800`}>
        {markdown ? (
          <div className="leading-6">{rendered}</div>
        ) : (
          <p className="m-0 text-gray-500">Itinerary details will appear here.</p>
        )}
      </div>
    </div>
  );
}

function renderMarkdownLite(markdown: string): ReactElement[] {
  const lines = markdown.split("\n");
  const blocks: ReactElement[] = [];
  let listItems: string[] = [];
  let table: string[][] = [];

  const flushList = () => {
    if (!listItems.length) return;
    blocks.push(
      <ul key={`list-${blocks.length}`} className="my-2 list-disc pl-5">
        {listItems.map((item, idx) => (
          <li key={idx}>{item}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  const flushTable = () => {
    if (!table.length) return;
    const [header, ...rows] = table;
    blocks.push(
      <div key={`table-${blocks.length}`} className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              {header.map((cell, idx) => (
                <th key={idx} className="border border-gray-200 bg-gray-50 px-2 py-1 text-left">{cell}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rIdx) => (
              <tr key={rIdx}>
                {row.map((cell, cIdx) => (
                  <td key={cIdx} className="border border-gray-200 px-2 py-1">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    table = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      flushTable();
      continue;
    }
    if (line.startsWith("|") && line.endsWith("|")) {
      flushList();
      const cells = line
        .slice(1, -1)
        .split("|")
        .map((cell) => cell.trim());
      if (!cells.every((cell) => /^-+$/.test(cell))) {
        table.push(cells);
      }
      continue;
    }
    flushTable();
    if (line.startsWith("- ")) {
      listItems.push(line.slice(2));
      continue;
    }
    flushList();
    if (line.startsWith("### ")) {
      blocks.push(<h3 key={`h3-${blocks.length}`} className="mt-2 text-sm font-semibold">{line.slice(4)}</h3>);
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(<h3 key={`h2-${blocks.length}`} className="mt-2 text-sm font-semibold">{line.slice(3)}</h3>);
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push(<h3 key={`h1-${blocks.length}`} className="mt-2 text-sm font-semibold">{line.slice(2)}</h3>);
      continue;
    }
    blocks.push(<p key={`p-${blocks.length}`} className="my-1">{line}</p>);
  }
  flushList();
  flushTable();
  return blocks;
}
