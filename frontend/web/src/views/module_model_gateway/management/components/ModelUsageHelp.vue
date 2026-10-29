<template>
  <ElDrawer v-model="visible" title="客户端模型配置 · 使用说明" size="min(520px, 96vw)">
    <div class="usage-help">
      <section>
        <h3>1. 准备供应商模型</h3>
        <p>
          进入资源中心 → 供应商与模型，配置 API
          地址与密钥。保存后点击「测试并发现模型」，再启用供应商账号与需要的模型。
        </p>
      </section>
      <section>
        <h3>2. 为当前客户端授权</h3>
        <p>
          先确认右上角的当前客户端，再点击「授权模型」。选择供应商模型，填写公开模型编码（例如
          bid-qwen）与客户端显示名称。
        </p>
        <dl>
          <dt>公开模型编码</dt>
          <dd>客户端调用模型时使用的稳定标识，保存后不能修改。</dd>
          <dt>客户端可见 / 允许用户选择</dt>
          <dd>分别控制模型是否展示、用户能否主动切换。后台业务专用模型可以不展示。</dd>
          <dt>设为默认模型</dt>
          <dd>用于客户端默认选择；不替代业务路由。每个客户端只保留一个默认模型。</dd>
          <dt>排序</dt>
          <dd>数字越小越靠前。</dd>
        </dl>
      </section>
      <section>
        <h3>3. 配置业务路由</h3>
        <p>
          点击「配置路由」，按实际使用的业务分别配置默认聊天、文档理解、语义审核。选择已授权且启用的主模型，必要时按顺序添加降级模型。
        </p>
        <p>
          主模型调用失败时按路由策略尝试降级。勾选「允许用户选模型」后，该业务才允许使用用户选择的模型；需要工具的业务还应开启「允许工具调用」，并选用支持工具的模型。
        </p>
        <p>
          超时以秒为单位；最大输出 Token
          限制单次输出长度，应与所选模型能力匹配。保存同一业务场景会更新原路由。
        </p>
      </section>
      <section>
        <h3>4. 在客户端验证</h3>
        <p>
          重新进入客户端或刷新模型配置，确认名称、默认模型和可选范围，再分别发起实际使用的业务请求。连接测试只验证供应商连接，不能替代完整业务验证。
        </p>
      </section>
      <section>
        <h3>常见问题</h3>
        <p><b>没有可授权模型：</b>检查供应商账号和模型是否都已启用。</p>
        <p><b>客户端看不到模型：</b>确认当前客户端正确、授权已启用且勾选「客户端可见」。</p>
        <p>
          <b>已授权但业务无法调用：</b
          >检查对应业务路由、主模型授权状态和供应商连接；默认模型不能替代路由。
        </p>
        <p><b>API Key 在哪里填：</b>只在供应商连接里配置，客户端授权无需重复填写。</p>
      </section>
    </div>
  </ElDrawer>
</template>
<script setup lang="ts">
const visible = defineModel<boolean>({ default: false });
</script>
<style scoped>
.usage-help {
  color: var(--el-text-color-regular);
  font-size: 14px;
  line-height: 1.85;
}
.usage-help section + section {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
h3 {
  margin: 0 0 8px;
  font-size: 15px;
  color: var(--el-text-color-primary);
}
p {
  margin: 8px 0;
}
dt {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
dd {
  margin: 2px 0 12px;
}
</style>
