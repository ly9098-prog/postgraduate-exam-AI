"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type TableColumn<TData> = {
  id?: string;
  header?: ReactNode | (() => ReactNode);
  accessorKey?: keyof TData | string;
  cell?: (context: { row: { original: TData } }) => ReactNode;
};

export function DataTable<TData>({
  data,
  columns,
  emptyText = "暂无数据",
}: {
  data: TData[];
  columns: Array<TableColumn<TData>>;
  emptyText?: string;
}) {
  return (
    <div className="overflow-hidden rounded-3xl border border-[var(--color-border)] bg-white/70">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead className="bg-[var(--color-primary-light)] text-left text-xs uppercase tracking-[0.16em] text-[var(--color-primary-dark)]">
            <tr>
              {columns.map((column, index) => (
                <th key={column.id ?? index} className="px-4 py-3 font-bold">
                  {typeof column.header === "function" ? column.id : column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.length ? (
              data.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-[var(--color-border)] transition hover:bg-[rgba(237,241,245,0.55)]">
                  {columns.map((column, cellIndex) => {
                    const accessorKey = column.accessorKey ? String(column.accessorKey) : undefined;
                    const value = accessorKey ? (row as Record<string, unknown>)[accessorKey] : undefined;
                    return (
                      <td key={`${rowIndex}-${cellIndex}`} className={cn("px-4 py-3 align-middle text-[var(--color-text-primary)]")}>
                        {column.cell
                          ? column.cell({ row: { original: row } })
                          : value === undefined || value === null
                            ? "—"
                            : String(value)}
                      </td>
                    );
                  })}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length} className="px-4 py-14 text-center text-[var(--color-text-hint)]">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
