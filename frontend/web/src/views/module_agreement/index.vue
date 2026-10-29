<script setup lang="ts">
import { ref } from "vue";
import { ElMessageBox } from "element-plus";
import { useClientAppStore } from "@/store/modules/client-app.store";
import AgreementTable from "./components/AgreementTable.vue";
import SceneTable from "./components/SceneTable.vue";
const tab = ref("agreements");
const store = useClientAppStore();
async function beforeLeave() {
  if (!store.hasUnsavedChanges) return true;
  return ElMessageBox.confirm("当前内容尚未保存，是否放弃修改并切换？", "切换页签", {
    confirmButtonText: "放弃修改",
    cancelButtonText: "继续编辑",
  })
    .then(() => true)
    .catch(() => false);
}
</script>
<template>
  <main class="fa-full-height agreement-page">
    <ElTabs v-model="tab" :before-leave="beforeLeave"
      ><ElTabPane label="协议列表" name="agreements" /><ElTabPane label="使用场景" name="scenes"
    /></ElTabs>
    <AgreementTable v-if="tab === 'agreements'" /><SceneTable v-else />
  </main>
</template>
<style scoped>
.agreement-page {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.agreement-page > :deep(.el-tabs) {
  flex: none;
}
</style>
