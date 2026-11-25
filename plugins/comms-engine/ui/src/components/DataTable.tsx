// The database table every list on the page uses: search, a filter per column
// that has more than one value, sorting by any column, and, where a page allows
// it, a row to add one more. How a table is sorted and filtered is remembered in
// this browser only (localStorage), per table.
import { useMemo, useState, type ReactNode } from "react";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { Plus, Search } from "lucide-react";

export interface Col<T> {
  id: string; label: string;
  get?: (r: T) => unknown;          // the value it sorts and searches by
  cell?: (r: T) => ReactNode;       // what it shows; the value when absent
  num?: boolean; sort?: boolean;
}
export interface Filter<T> { label: string; get: (r: T) => unknown }
export interface AddRow { label: string; fields: { key: string; placeholder: string; grow?: number }[]; submit: (v: Record<string, string>) => Promise<boolean> }

const store = {
  get<V>(k: string, d: V): V { try { const v = localStorage.getItem("control." + k); return v ? (JSON.parse(v) as V) : d; } catch { return d; } },
  set(k: string, v: unknown) { try { localStorage.setItem("control." + k, JSON.stringify(v)); } catch { /* private window */ } },
};
const list = (v: unknown): string[] => ([] as unknown[]).concat(v ?? []).filter((x) => x !== "" && x != null).map(String);

export function DataTable<T>({ id, rows, cols, filters = [], text, onRow, empty = "Nothing here yet.", search = true, add }: {
  id: string; rows: T[]; cols: Col<T>[]; filters?: Filter<T>[]; text?: (r: T) => string; onRow?: (r: T) => void;
  empty?: string; search?: boolean; add?: AddRow;
}) {
  const saved = store.get<{ sorting?: SortingState; f?: Record<number, string> }>(`table.${id}`, {});
  const [q, setQ] = useState("");
  const [f, setF] = useState<Record<number, string>>(saved.f || {});
  const [sorting, setSorting] = useState<SortingState>(saved.sorting || []);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const save = (s: SortingState, ff: Record<number, string>) => store.set(`table.${id}`, { sorting: s, f: ff });

  const options = useMemo(() => filters.map((fl) => [...new Set(rows.flatMap((r) => list(fl.get(r))))].sort()), [rows, filters]);
  const shown = useMemo(() => {
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return rows.filter((r) => {
      for (const [i, v] of Object.entries(f)) if (v && filters[+i] && !list(filters[+i].get(r)).includes(v)) return false;
      if (!words.length) return true;
      const hay = (cols.map((c) => list(c.get ? c.get(r) : (r as Record<string, unknown>)[c.id]).join(" ")).join(" ") + " " + (text ? text(r) : "")).toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [rows, q, f, filters, cols, text]);

  const columns = useMemo<ColumnDef<T>[]>(() => cols.map((c) => ({
    id: c.id, header: c.label, enableSorting: c.sort !== false,
    accessorFn: (r: T) => { const v = c.get ? c.get(r) : (r as Record<string, unknown>)[c.id]; return v == null || v === "" ? undefined : Array.isArray(v) ? v.join(" ") : v; },
    sortUndefined: "last" as const,
    cell: (ctx) => (c.cell ? c.cell(ctx.row.original) : String(ctx.getValue() ?? "")),
    meta: { num: c.num },
  })), [cols]);

  const table = useReactTable({
    data: shown, columns, state: { sorting },
    onSortingChange: (u) => { const s = typeof u === "function" ? u(sorting) : u; setSorting(s); save(s, f); },
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
  });

  const submit = async () => {
    if (!add) return;
    if (await add.submit(draft)) setDraft({});
  };

  return (
    <div className="dt">
      {search || filters.some((_, i) => options[i]?.length > 1) ? (
        <div className="dt-bar">
          {search ? <label className="dt-search"><Search aria-hidden /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" aria-label="Search this table" /></label> : null}
          {filters.map((fl, i) => options[i]?.length > 1 ? (
            <select key={fl.label} className="select" aria-label={fl.label} value={f[i] || ""}
              onChange={(e) => { const ff = { ...f, [i]: e.target.value }; setF(ff); save(sorting, ff); }}>
              <option value="">{fl.label}: all</option>
              {options[i].map((o) => <option key={o}>{o}</option>)}
            </select>
          ) : null)}
          <span className="dt-count">{shown.length === rows.length ? `${rows.length} ${rows.length === 1 ? "row" : "rows"}` : `${shown.length} of ${rows.length}`}</span>
        </div>
      ) : null}
      <div className="dt-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const num = (h.column.columnDef.meta as { num?: boolean })?.num;
                  const can = h.column.getCanSort(), dir = h.column.getIsSorted();
                  return (
                    <th key={h.id} className={`${num ? "num " : ""}${can ? "sortable" : ""}`} onClick={can ? h.column.getToggleSortingHandler() : undefined}
                      aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}>
                      {flexRender(h.column.columnDef.header, h.getContext())}{dir ? <span className="sort">{dir === "asc" ? "↑" : "↓"}</span> : null}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length ? table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={onRow ? "click" : ""}
                onClick={onRow ? (e) => { if (!(e.target as HTMLElement).closest("a, button, input, select")) onRow(row.original); } : undefined}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={(cell.column.columnDef.meta as { num?: boolean })?.num ? "num" : ""}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            )) : <tr><td className="empty" colSpan={cols.length}>{empty}</td></tr>}
          </tbody>
          {add ? (
            <tfoot>
              <tr><td colSpan={cols.length}>
                <div className="addrow">
                  <span className="plus"><Plus size={15} aria-hidden />{add.label}</span>
                  {add.fields.map((fd) => (
                    <input key={fd.key} className="input" style={{ flexGrow: fd.grow || 1 }} placeholder={fd.placeholder} value={draft[fd.key] || ""}
                      onChange={(e) => setDraft({ ...draft, [fd.key]: e.target.value })} onKeyDown={(e) => e.key === "Enter" && submit()} aria-label={fd.placeholder} />
                  ))}
                  <button className="btn primary small" onClick={submit}>Add</button>
                </div>
              </td></tr>
            </tfoot>
          ) : null}
        </table>
      </div>
    </div>
  );
}
