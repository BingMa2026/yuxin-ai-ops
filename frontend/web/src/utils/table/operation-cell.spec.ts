import { describe, expect, it } from "vitest";
import {
  DEFAULT_MAX_INLINE_TABLE_OPERATIONS,
  renderTableOperationCell,
  type TableOperationAction,
} from "./index";

function actions(count: number): TableOperationAction[] {
  return Array.from({ length: count }, (_, index) => ({
    key: `action-${index}`,
    label: `操作${index + 1}`,
    artType: "custom" as const,
    icon: "ri:settings-3-line",
    run: () => undefined,
  }));
}

describe("renderTableOperationCell", () => {
  it("keeps at most two direct actions and uses one overflow menu", () => {
    expect(DEFAULT_MAX_INLINE_TABLE_OPERATIONS).toBe(2);

    const cell = renderTableOperationCell(actions(5));
    expect(Array.isArray(cell.children)).toBe(true);
    expect(cell.children).toHaveLength(3);
  });

  it("renders a single action directly without an overflow trigger", () => {
    const cell = renderTableOperationCell(actions(1));
    expect(cell.children).toHaveLength(1);
  });
});
