import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import FaButtonTable from "./index.vue";

describe("FaButtonTable", () => {
  it("renders a compact labelled button without external spacing", async () => {
    const wrapper = mount(FaButtonTable, {
      props: {
        type: "custom",
        icon: "ri:arrow-down-circle-line",
        label: "下架",
      },
      global: {
        stubs: {
          FaSvgIcon: {
            props: ["icon"],
            template: '<span data-test="icon"></span>',
          },
        },
      },
    });

    expect(wrapper.element.tagName).toBe("BUTTON");
    expect(wrapper.attributes("aria-label")).toBe("下架");
    expect(wrapper.attributes("title")).toBe("下架");
    expect(wrapper.classes()).not.toContain("mr-2.5");

    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toHaveLength(1);
  });

  it("does not emit when disabled", async () => {
    const wrapper = mount(FaButtonTable, {
      props: { type: "view", label: "详情", disabled: true },
      global: {
        stubs: {
          FaSvgIcon: true,
        },
      },
    });

    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toBeUndefined();
  });
});
