import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import FaIconButton from "./index.vue";

describe("FaIconButton", () => {
  it("renders a labelled native button", async () => {
    const wrapper = mount(FaIconButton, {
      props: {
        icon: "ri:menu-2-fill",
        label: "收起侧边栏",
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
    expect(wrapper.attributes("type")).toBe("button");
    expect(wrapper.attributes("aria-label")).toBe("收起侧边栏");
    expect(wrapper.attributes("title")).toBe("收起侧边栏");
    expect(wrapper.get('[data-test="icon"]').element).toBeTruthy();

    await wrapper.trigger("click");
    expect(wrapper.emitted("click")).toHaveLength(1);
  });
});
