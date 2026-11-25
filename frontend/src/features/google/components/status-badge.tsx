import type { DisplayStatus } from "../types";
import { STATUS_CLASS, STATUS_HELP, STATUS_LABEL } from "../lib/labels";

export function StatusBadge({ status }: { status: DisplayStatus }) {
  return (
    <span
      title={STATUS_HELP[status]}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}
