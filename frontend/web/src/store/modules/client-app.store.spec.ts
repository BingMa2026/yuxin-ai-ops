import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useClientAppStore } from "./client-app.store";

describe("client app store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("tracks unsaved editors without duplicating sources", () => {
    const store = useClientAppStore();

    store.markDirty("catalog", true);
    store.markDirty("catalog", true);
    expect(store.hasUnsavedChanges).toBe(true);
    store.markDirty("catalog", false);
    expect(store.hasUnsavedChanges).toBe(false);

    store.markDirty("model", true);
    expect(store.hasUnsavedChanges).toBe(true);
    store.clearDirty();
    expect(store.hasUnsavedChanges).toBe(false);
  });
});
