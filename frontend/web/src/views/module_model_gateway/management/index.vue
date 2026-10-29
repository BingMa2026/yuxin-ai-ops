<template>
  <main class="model-workspace fa-full-height">
    <section v-if="workspace === 'platform'" class="platform-layout">
      <aside class="provider-panel">
        <div class="provider-search">
          <ElInput v-model="providerKeyword" clearable placeholder="搜索供应商"
            ><template #prefix><FaSvgIcon icon="ri:search-line" /></template
          ></ElInput>
          <ElButton
            :loading="platformLoading"
            aria-label="刷新供应商"
            title="刷新供应商"
            @click="loadPlatform"
            ><FaSvgIcon icon="ri:refresh-line"
          /></ElButton>
        </div>
        <div class="provider-filter">
          <button :class="{ active: providerFilter === 'all' }" @click="providerFilter = 'all'">
            全部</button
          ><button
            :class="{ active: providerFilter === 'configured' }"
            @click="providerFilter = 'configured'"
          >
            已配置</button
          ><button
            :class="{ active: providerFilter === 'pending' }"
            @click="providerFilter = 'pending'"
          >
            待配置
          </button>
        </div>
        <div class="provider-list" v-loading="platformLoading">
          <button
            v-for="item in filteredTemplates"
            :key="item.id"
            class="provider-item"
            :class="{ active: selectedTemplate?.id === item.id }"
            @click="selectedTemplate = item"
          >
            <ProviderLogo :code="item.code" :name="item.name" />
            <span
              ><strong>{{ item.name }}</strong
              ><small>{{
                accountFor(item)?.connection_status === "healthy"
                  ? "连接正常"
                  : accountFor(item)
                    ? "需要测试"
                    : "尚未配置"
              }}</small></span
            >
            <i :class="accountFor(item)?.connection_status === 'healthy' ? 'healthy' : ''"></i>
          </button>
        </div>
        <ElEmpty
          v-if="!platformLoading && !filteredTemplates.length"
          :image-size="48"
          description="没有匹配的供应商"
        />
      </aside>

      <section v-if="selectedTemplate" class="provider-detail">
        <header class="provider-hero">
          <ProviderLogo :code="selectedTemplate.code" :name="selectedTemplate.name" large />
          <div>
            <div>
              <h2>{{ selectedTemplate.name }}</h2>
              <ElTag v-if="!selectedTemplate.adapter_ready" type="info">适配器未启用</ElTag
              ><ElTag
                v-else
                :type="selectedAccount?.connection_status === 'healthy' ? 'success' : 'warning'"
                >{{
                  selectedAccount?.connection_status === "healthy"
                    ? "连接正常"
                    : selectedAccount
                      ? "待测试"
                      : "待配置"
                }}</ElTag
              >
            </div>
            <p>{{ selectedTemplate.description }}</p>
            <span>{{
              selectedTemplate.protocol === "openai_compatible"
                ? "OpenAI 兼容协议"
                : `${selectedTemplate.protocol} 原生协议`
            }}</span>
          </div>
          <div class="hero-actions">
            <ElButton
              type="primary"
              :disabled="!selectedTemplate.adapter_ready"
              @click="openProvider(selectedAccount)"
              >{{ selectedAccount ? "编辑连接" : "配置连接" }}</ElButton
            ><ElButton
              v-if="selectedAccount"
              :loading="testingId === selectedAccount.id"
              :disabled="discovering || togglingAccount"
              @click="testAndDiscover(selectedAccount)"
              >测试并发现模型</ElButton
            ><ElButton
              v-if="selectedAccount?.connection_status === 'healthy'"
              :type="selectedAccount.status === 'active' ? 'danger' : 'success'"
              :loading="togglingAccount"
              :disabled="discovering"
              plain
              @click="toggleAccount(Number(selectedAccount.id), selectedAccount.status)"
              >{{ selectedAccount.status === "active" ? "停用账号" : "启用账号" }}</ElButton
            >
          </div>
        </header>
        <div class="connection-card">
          <div>
            <span>API 地址</span
            ><strong>{{
              selectedAccount?.endpoint || selectedTemplate.default_endpoint || "配置时填写服务地址"
            }}</strong>
          </div>
          <div>
            <span>密钥</span
            ><strong>{{ selectedAccount ? maskSummary(selectedAccount) : "未配置" }}</strong>
          </div>
          <div>
            <span>推荐模型</span
            ><strong>{{ selectedTemplate.recommended_model || "按供应商目录选择" }}</strong>
          </div>
          <div>
            <span>最后测试</span
            ><strong>{{ selectedAccount?.last_verified_at || "从未测试" }}</strong>
          </div>
        </div>
        <section v-if="selectedAccount" class="finance-card">
          <header class="section-head">
            <div>
              <strong>财务与余额</strong>
              <span>财务凭据独立加密，仅用于余额、账单和成本核对</span>
            </div>
            <div class="finance-actions">
              <ElButton @click="openFinance">{{
                financeSummary?.profile ? "编辑财务连接" : "配置财务连接"
              }}</ElButton>
              <ElButton
                :disabled="!financeSummary?.profile || financeSummary.profile.status !== 'active'"
                :loading="financeTesting"
                @click="testFinance"
                >测试财务连接</ElButton
              >
              <ElButton
                type="primary"
                plain
                :disabled="!financeSummary?.profile || financeSummary.profile.status !== 'active'"
                :loading="financeSyncing"
                @click="syncFinance"
                >同步余额与账单</ElButton
              >
            </div>
          </header>
          <div class="finance-metrics">
            <div>
              <span>账户余额</span>
              <strong v-if="financeSummary?.latest_balance">{{
                financeMoney(financeSummary.latest_balance.amount_yuan)
              }}</strong>
              <strong v-else>—</strong>
              <small>{{
                financeSummary?.latest_balance
                  ? `${financeSummary.latest_balance.currency} · ${formatDate(financeSummary.latest_balance.fetched_at)}`
                  : balanceCapabilityText
              }}</small>
            </div>
            <div>
              <span>本月供应商账单</span
              ><strong>{{ financeMoney(financeSummary?.month_bill_yuan) }}</strong>
              <small>{{
                financeSummary?.last_bill_at
                  ? `账单至 ${formatDate(financeSummary.last_bill_at)}`
                  : "尚未同步账单"
              }}</small>
            </div>
            <div>
              <span>本月请求成本</span
              ><strong>{{
                financeSummary?.month_request_count === 0
                  ? "—"
                  : financeMoney(financeSummary?.request_cost_yuan, 4)
              }}</strong>
              <small>{{
                financeSummary?.month_request_count === 0
                  ? "本月暂无归属该供应商的请求记录"
                  : `含语音 ${financeMoney(financeSummary?.speech_cost_yuan, 4)}；按调用时价格计算`
              }}</small>
              <small v-if="financeSummary?.unknown_cost_calls"
                >另有 {{ financeSummary.unknown_cost_calls }} 次成本待确认</small
              >
            </div>
            <div>
              <span>成本核对</span
              ><strong>{{
                !financeSummary
                  ? "—"
                  : financeSummary.unknown_cost_calls
                    ? "成本待确认"
                    : financeSummary.month_request_count === 0 ||
                        !financeSummary.last_bill_at ||
                        financeSummary.request_cost_yuan <= 0
                      ? "待核对"
                      : `${financeSummary.reconciliation_coverage_rate.toFixed(1)}%`
              }}</strong>
              <small v-if="financeSummary?.month_request_count === 0"
                >需有平台请求记录后才能与供应商账单核对</small
              >
              <small v-else-if="!financeSummary?.last_bill_at">尚未同步账单</small>
              <small v-else-if="financeSummary.request_cost_yuan <= 0">暂无可核对的请求成本</small>
              <small v-else>差异 {{ signedMoney(financeSummary?.difference_yuan) }}</small>
            </div>
          </div>
          <div v-if="financeSummary?.profile?.capabilities.resource_pack" class="resource-packages">
            <span class="resource-packages__label">有效资源包</span>
            <div v-if="financeSummary.resource_packages.length" class="resource-packages__list">
              <ElTag
                v-for="item in financeSummary.resource_packages"
                :key="item.external_id"
                effect="plain"
              >
                {{ item.name }} · {{ Number(item.remaining_amount).toLocaleString("zh-CN") }}
                {{ item.unit }}
                <template v-if="item.expires_at">
                  · {{ dayjs(item.expires_at).format("YYYY-MM-DD") }} 到期</template
                >
              </ElTag>
            </div>
            <small v-else>未查询到有效资源包</small>
          </div>
          <ElAlert
            v-if="financeSummary?.profile?.last_error"
            type="warning"
            :closable="false"
            :title="financeSummary.profile.last_error"
            show-icon
          />
        </section>
        <div class="model-section">
          <div class="model-tools">
            <div>
              <strong>模型目录</strong><span>{{ selectedModels.length }} 个模型</span>
            </div>
            <div>
              <ElInput v-model="modelKeyword" clearable placeholder="搜索模型" /><ElSelect
                v-model="modelStatus"
                clearable
                placeholder="全部状态"
                ><ElOption label="启用" value="active" /><ElOption
                  label="停用"
                  value="inactive" /></ElSelect
              ><ElSelect v-model="modelKind" clearable placeholder="全部类型"
                ><ElOption label="对话模型" value="chat" /><ElOption
                  label="其他模型"
                  value="other" /></ElSelect
              ><ElButton :disabled="!selectedAccount" @click="openModel()"
                ><FaSvgIcon icon="ri:add-line" />手工添加</ElButton
              ><ElButton
                type="primary"
                :disabled="!selectedAccount"
                :loading="discovering"
                @click="discoverSelected"
                ><FaSvgIcon icon="ri:download-cloud-2-line" />刷新目录</ElButton
              >
            </div>
          </div>
          <div class="model-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>模型</th>
                  <th>上下文</th>
                  <th>能力</th>
                  <th class="cost-column">普通输入<br /><small>元/百万 Token</small></th>
                  <th class="cost-column">缓存读取<br /><small>元/百万 Token</small></th>
                  <th class="cost-column">缓存写入<br /><small>元/百万 Token</small></th>
                  <th class="cost-column">模型输出<br /><small>元/百万 Token</small></th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in pagedModels" :key="item.id">
                  <td>
                    <strong>{{ item.display_name }}</strong
                    ><small>{{ item.provider_model_id }}</small>
                  </td>
                  <td>{{ item.context_length?.toLocaleString() || "—" }}</td>
                  <td>
                    <div class="capabilities">
                      <ElTag v-if="item.supports_stream" size="small">流式</ElTag
                      ><ElTag v-if="item.supports_tools" size="small" type="success">工具</ElTag
                      ><ElTag v-if="item.supports_vision" size="small" type="warning">视觉</ElTag
                      ><ElTag v-if="item.supports_pdf" size="small" type="info">PDF</ElTag
                      ><ElTag
                        v-if="
                          item.speech_protocol || !isChatGatewayCompatible(item.provider_model_id)
                        "
                        size="small"
                        type="info"
                        >{{
                          item.speech_protocol || isSpeechInputModel(item.provider_model_id)
                            ? "语音识别"
                            : item.provider_model_id.includes("-tts")
                              ? "语音合成（待接入）"
                              : "非对话"
                        }}</ElTag
                      >
                    </div>
                  </td>
                  <td
                    v-if="
                      item.speech_pricing ||
                      item.speech_protocol ||
                      isSpeechInputModel(item.provider_model_id) ||
                      /tts|omni|audio|speech-/i.test(item.provider_model_id)
                    "
                    colspan="4"
                  >
                    <SpeechPriceSummary :pricing="item.speech_pricing" />
                  </td>
                  <template v-else>
                    <td class="cost-value-cell">
                      <strong v-if="hasVerifiedCost(item)">{{
                        formatCost(item.input_cost_per_million)
                      }}</strong>
                      <ElTag v-else size="small" type="warning" effect="plain">待配置</ElTag>
                    </td>
                    <td class="cost-value-cell">
                      <strong v-if="hasVerifiedCost(item)">{{
                        formatCost(item.cache_read_cost_per_million)
                      }}</strong>
                      <span v-else>—</span>
                    </td>
                    <td class="cost-value-cell">
                      <strong v-if="hasVerifiedCost(item)">{{
                        formatCost(item.cache_write_cost_per_million)
                      }}</strong>
                      <span v-else>—</span>
                    </td>
                    <td class="cost-value-cell">
                      <strong v-if="hasVerifiedCost(item)">{{
                        formatCost(item.output_cost_per_million)
                      }}</strong>
                      <span v-else>—</span>
                    </td>
                  </template>
                  <td>
                    <ElTag :type="item.status === 'active' ? 'success' : 'info'">{{
                      item.status === "active" ? "已启用" : "已停用"
                    }}</ElTag>
                  </td>
                  <td>
                    <ElButton
                      v-if="
                        !item.speech_pricing &&
                        !(item.speech_protocol || isSpeechInputModel(item.provider_model_id))
                      "
                      link
                      type="primary"
                      @click="openPrice(item)"
                      >{{ hasVerifiedCost(item) ? "价格版本" : "配置价格" }}</ElButton
                    ><ElButton link type="primary" @click="openModel(item)">编辑</ElButton
                    ><ElButton
                      link
                      :type="item.status === 'active' ? 'danger' : 'success'"
                      :loading="togglingModelId === item.id"
                      :disabled="
                        (togglingModelId !== undefined && togglingModelId !== item.id) ||
                        (!!item.speech_protocol &&
                          isChatGatewayCompatible(item.provider_model_id) &&
                          !(item.speech_protocol || isSpeechInputModel(item.provider_model_id)) &&
                          item.status !== 'active')
                      "
                      @click="toggleModel(Number(item.id), item.status !== 'active')"
                      >{{ item.status === "active" ? "停用" : "启用" }}</ElButton
                    >
                  </td>
                </tr>
              </tbody>
            </table>
            <ElEmpty
              v-if="!filteredModels.length"
              :image-size="72"
              :description="
                modelKeyword || modelStatus || modelKind
                  ? '没有符合筛选条件的模型'
                  : selectedAccount
                    ? '测试连接并发现模型后，在这里启用需要的模型'
                    : '先配置供应商连接，再获取可用模型'
              "
            />
            <div v-if="filteredModels.length" class="model-pagination">
              <span>共 {{ filteredModels.length }} 个模型</span>
              <ElPagination
                v-model:current-page="modelPage"
                v-model:page-size="modelPageSize"
                background
                layout="sizes, prev, pager, next"
                :page-sizes="[20, 50, 100]"
                :total="filteredModels.length"
              />
            </div>
          </div>
        </div>
      </section>
    </section>

    <section v-else class="client-layout" v-loading="loading">
      <div v-if="!currentApp" class="empty-client">
        <ElEmpty description="请先在右上角选择客户端" />
      </div>
      <template v-else>
        <div v-show="configurationTab === 'chat'" class="setup-guide">
          <div><b>1 · 授权模型</b><span>选择已启用的供应商模型</span></div>
          <div><b>2 · 配置业务路由</b><span>为聊天、文档理解、语义审核指定模型</span></div>
          <div><b>3 · 客户端验证</b><span>实际发起一次对应业务请求</span></div>
        </div>
        <ElAlert
          v-if="configurationTab === 'chat' && !activeModels.length && !loading"
          title="暂无可授权模型，请先在「供应商与模型」中测试连接并启用账号和模型。"
          type="info"
          :closable="false"
          show-icon
        />
        <section class="client-models">
          <div class="section-head">
            <div><strong>模型配置</strong><span>按用途配置当前客户端使用的模型</span></div>
            <div v-if="configurationTab === 'chat'" class="client-model-actions">
              <ElButton @click="helpVisible = true"
                ><FaSvgIcon icon="ri:question-line" />使用说明</ElButton
              >
              <ElButton type="primary" :disabled="!activeModels.length" @click="openBinding()"
                ><FaSvgIcon icon="ri:add-line" />授权模型</ElButton
              >
            </div>
          </div>
          <ElTabs v-model="configurationTab" aria-label="模型配置用途">
            <ElTabPane label="对话模型" name="chat">
              <div class="binding-grid">
                <article v-for="item in bindings" :key="item.id">
                  <div>
                    <span class="model-mark"><FaSvgIcon icon="ri:cpu-line" /></span
                    ><span
                      ><strong>{{ item.client_display_name }}</strong
                      ><small>{{ item.public_model_code }}</small></span
                    >
                  </div>
                  <div class="binding-tags">
                    <ElTag v-if="item.is_default" type="success">默认</ElTag
                    ><ElTag v-if="item.user_selectable">用户可选</ElTag
                    ><ElTag :type="item.status === 'active' ? 'success' : 'info'">{{
                      item.status === "active" ? "已启用" : "已停用"
                    }}</ElTag>
                  </div>
                  <div class="card-actions">
                    <ElButton link @click="openBinding(item)">编辑</ElButton
                    ><ElButton
                      link
                      :type="item.status === 'active' ? 'danger' : 'success'"
                      @click="toggleBinding(Number(item.id), item.status !== 'active')"
                      >{{ item.status === "active" ? "停用" : "启用" }}</ElButton
                    >
                  </div>
                </article>
                <ElEmpty v-if="!bindings.length" :image-size="64" description="尚未授权模型" />
              </div>
            </ElTabPane>
            <ElTabPane label="语音输入" name="speech">
              <SpeechConfig
                v-if="currentApp.id"
                :key="currentApp.id"
                :app-id="currentApp.id"
                :app-name="currentApp.name"
              />
            </ElTabPane>
          </ElTabs>
        </section>
        <section v-show="configurationTab === 'chat'" class="route-section">
          <div class="section-head">
            <div><strong>业务路由</strong><span>统一配置主模型和降级顺序</span></div>
            <ElButton type="primary" :disabled="!activeBindings.length" @click="openRoute()"
              ><FaSvgIcon icon="ri:route-line" />配置路由</ElButton
            >
          </div>
          <div class="route-list">
            <article v-for="item in routes" :key="item.id">
              <span class="route-icon"><FaSvgIcon :icon="businessIcon(item.business_code)" /></span>
              <div>
                <strong>{{ item.name }}</strong
                ><small>{{ businessName(item.business_code) }}</small>
              </div>
              <div class="route-flow">
                <b>{{ bindingName(item.primary_binding_id) }}</b
                ><template v-for="fallback in item.fallback_binding_ids" :key="fallback"
                  ><FaSvgIcon icon="ri:arrow-right-line" /><span>{{
                    bindingName(fallback)
                  }}</span></template
                >
              </div>
              <ElTag :type="item.status === 'active' ? 'success' : 'info'">{{
                item.status === "active" ? "执行中" : "未启用"
              }}</ElTag
              ><ElButton link @click="openRoute(item)">编辑</ElButton>
            </article>
            <ElEmpty
              v-if="!routes.length"
              :image-size="64"
              description="尚未配置路由，请为客户端使用的业务场景指定主模型"
            />
          </div>
        </section>
      </template>
    </section>

    <ModelUsageHelp v-model="helpVisible" />
    <ProviderAccountDialog
      v-model="providerDialog"
      :templates="selectedTemplate ? [selectedTemplate] : templates"
      :account="editingAccount"
      :saving="saving"
      @save="saveAccount"
    />
    <ElDialog
      v-model="financeDialog"
      title="供应商财务连接"
      width="min(660px,94vw)"
      destroy-on-close
    >
      <ElForm label-position="top">
        <ElAlert
          title="财务凭据与推理密钥完全隔离；保存后仅显示掩码。"
          type="info"
          :closable="false"
        />
        <div class="form-grid finance-form">
          <ElFormItem label="财务适配器">
            <ElSelect v-model="financeForm.adapter_type" @change="resetFinanceSettings">
              <ElOption
                v-for="item in financeAdapterOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="余额告警线（人民币）"
            ><ElInputNumber v-model="financeForm.balance_warning_yuan" :min="0" :precision="2"
          /></ElFormItem>
          <template v-for="field in financeFields" :key="field.key">
            <ElFormItem>
              <template #label>
                <span class="finance-field-label">
                  {{ field.label }}
                  <ElTooltip v-if="field.help" :content="field.help" placement="top">
                    <a
                      class="finance-field-help"
                      :href="field.docsUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      :aria-label="`查看${field.label}获取说明`"
                      ><FaSvgIcon icon="ri:error-warning-line"
                    /></a>
                  </ElTooltip>
                </span>
              </template>
              <ElInput
                v-model="financeForm.settings[field.key]"
                :type="field.secret ? 'password' : 'text'"
                :placeholder="field.placeholder"
                show-password
              />
            </ElFormItem>
          </template>
          <div v-if="financeForm.adapter_type === 'alibaba_bss'" class="finance-access-guide">
            建议新建专用 RAM 用户，授予 <code>AliyunBSSReadOnlyAccess</code> 后再创建 AccessKey；
            请勿填写百炼模型调用 API Key。
            <a
              href="https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair"
              target="_blank"
              rel="noopener noreferrer"
              >查看阿里云获取步骤</a
            >
            <a
              href="https://help.aliyun.com/zh/model-studio/permission-management-overview"
              target="_blank"
              rel="noopener noreferrer"
              >查看账单权限说明</a
            >
          </div>
          <ElFormItem v-if="needsExchangeRate" label="兑人民币汇率">
            <ElInputNumber
              v-model="financeForm.settings.exchange_rate_to_cny"
              :min="0.000001"
              :precision="6"
            />
          </ElFormItem>
        </div>
      </ElForm>
      <template #footer
        ><ElButton @click="financeDialog = false">取消</ElButton
        ><ElButton type="primary" :loading="financeSaving" @click="saveFinance"
          >保存连接</ElButton
        ></template
      >
    </ElDialog>
    <ElDialog
      v-model="priceDialog"
      :title="`${priceModel?.display_name || ''} · 采购价格版本`"
      width="min(820px,96vw)"
      destroy-on-close
    >
      <div class="price-history">
        <div v-for="item in modelPrices" :key="item.id" class="price-history__item">
          <span
            ><b>{{ item.currency }}</b
            ><small>{{ formatDate(item.effective_from) }} 起 · {{ item.source }}</small></span
          >
          <span>普通输入 {{ item.input_cost_per_million }}</span
          ><span>缓存读取 {{ item.cache_read_cost_per_million }}</span
          ><span>缓存写入 {{ item.cache_write_cost_per_million }}</span
          ><span>模型输出 {{ item.output_cost_per_million }}</span>
          <ElTag :type="item.status === 'active' ? 'success' : 'info'">{{
            item.status === "active" ? "当前" : "历史"
          }}</ElTag>
        </div>
        <ElEmpty
          v-if="!modelPrices.length"
          :image-size="54"
          description="暂无版本，将使用目录价格并保存请求快照"
        />
      </div>
      <ElDivider content-position="left">新增价格版本</ElDivider>
      <ElForm label-position="top"
        ><div class="form-grid">
          <ElFormItem label="区域"
            ><ElInput v-model="priceForm.region" placeholder="留空表示全部区域"
          /></ElFormItem>
          <ElFormItem label="服务档位"
            ><ElSelect v-model="priceForm.service_tier"
              ><ElOption label="标准实时" value="standard" /><ElOption
                label="优先级"
                value="priority" /><ElOption label="灵活处理" value="flex" /></ElSelect
          ></ElFormItem>
          <ElFormItem label="调用模式"
            ><ElSelect v-model="priceForm.billing_mode"
              ><ElOption label="实时调用" value="realtime" /><ElOption
                label="Batch 批处理"
                value="batch" /><ElOption label="资源包抵扣" value="resource_pack" /></ElSelect
          ></ElFormItem>
          <ElFormItem label="上下文区间"
            ><div class="context-range">
              <ElInputNumber v-model="priceForm.context_min" :min="0" /><span>至</span
              ><ElInputNumber v-model="priceForm.context_max" :min="1" placeholder="不限" /></div
          ></ElFormItem>
          <ElFormItem label="币种"
            ><ElSelect v-model="priceForm.currency"
              ><ElOption label="人民币 CNY" value="CNY" /><ElOption
                label="美元 USD"
                value="USD" /></ElSelect
          ></ElFormItem>
          <ElFormItem label="兑人民币汇率"
            ><ElInputNumber v-model="priceForm.exchange_rate_to_cny" :min="0.000001" :precision="6"
          /></ElFormItem>
          <ElFormItem label="普通输入 / 百万 Token"
            ><ElInputNumber v-model="priceForm.input_cost_per_million" :min="0" :precision="6"
          /></ElFormItem>
          <ElFormItem label="缓存读取 / 百万 Token"
            ><ElInputNumber v-model="priceForm.cache_read_cost_per_million" :min="0" :precision="6"
          /></ElFormItem>
          <ElFormItem label="缓存写入 / 百万 Token"
            ><ElInputNumber
              v-model="priceForm.cache_write_cost_per_million"
              :min="0"
              :precision="6"
          /></ElFormItem>
          <ElFormItem label="输出 / 百万 Token"
            ><ElInputNumber v-model="priceForm.output_cost_per_million" :min="0" :precision="6"
          /></ElFormItem>
          <ElFormItem label="推理 Token / 百万 Token"
            ><ElInputNumber v-model="priceForm.reasoning_cost_per_million" :min="0" :precision="6"
          /></ElFormItem>
          <ElFormItem label="生效时间"
            ><ElDatePicker
              v-model="priceForm.effective_from"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ssZ"
          /></ElFormItem></div
      ></ElForm>
      <template #footer
        ><ElButton @click="priceDialog = false">关闭</ElButton
        ><ElButton type="primary" :loading="priceSaving" @click="savePrice"
          >发布价格版本</ElButton
        ></template
      >
    </ElDialog>
    <ElDialog
      v-model="modelDialog"
      :title="editingModel ? '编辑模型' : '手工添加模型'"
      width="min(680px,94vw)"
      destroy-on-close
      ><ElForm label-position="top"
        ><div class="form-grid">
          <ElFormItem label="供应商账号"
            ><ElSelect v-model="modelForm.provider_account_id" :disabled="!!editingModel"
              ><ElOption
                v-for="item in accounts"
                :key="item.id"
                :label="item.name"
                :value="item.id || 0" /></ElSelect></ElFormItem
          ><ElFormItem label="供应商模型 ID"
            ><ElInput
              v-model="modelForm.provider_model_id"
              :disabled="!!editingModel" /></ElFormItem
          ><ElFormItem label="显示名称"><ElInput v-model="modelForm.display_name" /></ElFormItem
          ><ElFormItem label="上下文长度"
            ><ElInputNumber v-model="modelForm.context_length" :min="1" /></ElFormItem
          ><ElFormItem label="输入成本 / 百万 Token"
            ><ElInputNumber
              v-model="modelForm.input_cost_per_million"
              :min="0"
              :precision="6" /></ElFormItem
          ><ElFormItem label="输出成本 / 百万 Token"
            ><ElInputNumber
              v-model="modelForm.output_cost_per_million"
              :min="0"
              :precision="6" /></ElFormItem
          ><ElFormItem label="输入积分 / 1K Token"
            ><ElInputNumber v-model="modelForm.input_credits_per_1k" :min="0" /></ElFormItem
          ><ElFormItem label="输出积分 / 1K Token"
            ><ElInputNumber v-model="modelForm.output_credits_per_1k" :min="0"
          /></ElFormItem>
        </div>
        <SpeechModelSettings
          v-model:protocol="modelForm.speech_protocol"
          v-model:pricing="modelForm.speech_pricing"
        />
        <div class="feature-checks">
          <ElCheckbox v-model="modelForm.supports_stream">流式输出</ElCheckbox
          ><ElCheckbox v-model="modelForm.supports_tools">工具调用</ElCheckbox
          ><ElCheckbox v-model="modelForm.supports_vision">图片理解</ElCheckbox
          ><ElCheckbox v-model="modelForm.supports_pdf">PDF</ElCheckbox>
        </div></ElForm
      ><template #footer
        ><ElButton @click="modelDialog = false">取消</ElButton
        ><ElButton type="primary" :loading="saving" @click="saveModel">保存</ElButton></template
      ></ElDialog
    >
    <ElDialog
      v-model="bindingDialog"
      :title="editingBinding ? '编辑客户端模型' : '授权模型给当前客户端'"
      width="min(680px,94vw)"
      destroy-on-close
      ><ElForm label-position="top"
        ><ElFormItem label="目录模型"
          ><ElSelect v-model="bindingForm.catalog_model_id" :disabled="!!editingBinding"
            ><ElOption
              v-for="item in activeModels"
              :key="item.id"
              :label="`${item.display_name} · ${item.provider_model_id}`"
              :value="item.id || 0" /></ElSelect
        ></ElFormItem>
        <div class="form-grid">
          <ElFormItem label="公开模型编码"
            ><ElInput
              placeholder="例如 bid-qwen，保存后不可修改"
              v-model="bindingForm.public_model_code"
              :disabled="!!editingBinding" /></ElFormItem
          ><ElFormItem label="客户端显示名称"
            ><ElInput
              v-model="bindingForm.client_display_name"
              placeholder="例如：千问 · 标书助手" /></ElFormItem
          ><ElFormItem label="排序"
            ><ElInputNumber v-model="bindingForm.order" :min="0"
          /></ElFormItem>
        </div>
        <p class="field-help">
          可见：展示在客户端；允许选择：用户可切换；默认：未指定模型时使用。业务路由仍需单独配置。
        </p>
        <div class="feature-checks">
          <ElCheckbox v-model="bindingForm.visible">客户端可见</ElCheckbox
          ><ElCheckbox v-model="bindingForm.user_selectable">允许用户选择</ElCheckbox
          ><ElCheckbox v-model="bindingForm.is_default">设为默认模型</ElCheckbox>
        </div></ElForm
      ><template #footer
        ><ElButton @click="bindingDialog = false">取消</ElButton
        ><ElButton type="primary" :loading="saving" @click="saveBinding">保存</ElButton></template
      ></ElDialog
    >
    <ElDialog v-model="routeDialog" title="配置业务路由" width="min(620px,94vw)" destroy-on-close
      ><ElForm label-position="top"
        ><div class="form-grid">
          <ElFormItem label="业务场景"
            ><ElSelect v-model="routeForm.business_code"
              ><ElOption label="默认聊天" value="chat_default" /><ElOption
                label="文档理解"
                value="document_intelligence" /><ElOption
                label="语义审核"
                value="semantic_review" /></ElSelect></ElFormItem
          ><ElFormItem label="路由名称"><ElInput v-model="routeForm.name" /></ElFormItem>
        </div>
        <ElFormItem label="主模型"
          ><ElSelect v-model="routeForm.primary_binding_id"
            ><ElOption
              v-for="item in activeBindings"
              :key="item.id"
              :label="item.client_display_name"
              :value="item.id || 0" /></ElSelect></ElFormItem
        ><ElFormItem label="降级模型（按顺序）"
          ><ElSelect v-model="routeForm.fallback_binding_ids" multiple
            ><ElOption
              v-for="item in activeBindings.filter(
                (entry) => entry.id !== routeForm.primary_binding_id
              )"
              :key="item.id"
              :label="item.client_display_name"
              :value="item.id || 0" /></ElSelect
        ></ElFormItem>
        <div class="form-grid">
          <ElFormItem label="回答上限（Token）"
            ><ElInputNumber
              v-model="routeForm.max_output_tokens"
              :min="1"
              :max="131072" /></ElFormItem
          ><ElFormItem label="无响应超时（秒）"
            ><ElInputNumber v-model="routeForm.timeout_seconds" :min="1" :max="1800"
          /></ElFormItem>
        </div>
        <RouteGenerationPolicy
          v-model="routeForm.generation_settings"
          :max-output-tokens="routeForm.max_output_tokens"
        />
        <div class="feature-checks">
          <ElCheckbox v-model="routeForm.allow_tools">允许工具调用</ElCheckbox
          ><ElCheckbox v-model="routeForm.allow_user_model">允许用户选模型</ElCheckbox>
        </div></ElForm
      ><template #footer
        ><ElButton @click="routeDialog = false">取消</ElButton
        ><ElButton type="primary" :loading="saving" @click="saveRoute"
          >保存并启用</ElButton
        ></template
      ></ElDialog
    >
  </main>
</template>

<script setup lang="ts">
import dayjs from "dayjs";
import { ElMessage } from "element-plus";
import ModelGatewayAPI, {
  type CatalogModel,
  type FinanceSummary,
  type ModelBinding,
  type ModelRoute,
  type ProviderAccount,
  type ProviderTemplate,
  type PurchasePrice,
} from "@/api/module_model_gateway";
import { useClientAppStore } from "@stores";
import ProviderLogo from "./components/ProviderLogo.vue";
import ModelUsageHelp from "./components/ModelUsageHelp.vue";
import ProviderAccountDialog from "./components/ProviderAccountDialog.vue";
import type { SpeechPricing } from "@/api/module_model_gateway";
import SpeechModelSettings from "./components/SpeechModelSettings.vue";
import SpeechPriceSummary from "./components/SpeechPriceSummary.vue";
import SpeechConfig from "./components/SpeechConfig.vue";
import RouteGenerationPolicy from "./components/RouteGenerationPolicy.vue";
import type { GenerationSettings } from "@/api/module_model_gateway";
import {
  isChatGatewayCompatible,
  isSpeechInputModel,
  sortCatalogModels,
  sortProviderTemplates,
} from "./model-order";
defineOptions({ name: "ModelManagement" });
const clientAppStore = useClientAppStore();
const { currentApp } = storeToRefs(clientAppStore);
const props = withDefaults(defineProps<{ workspace?: "platform" | "client" }>(), {
  workspace: "platform",
});
const workspace = computed(() => props.workspace);
const helpVisible = ref(false);
const configurationTab = ref("chat");
const templates = ref<ProviderTemplate[]>([]);
const accounts = ref<ProviderAccount[]>([]);
const models = ref<CatalogModel[]>([]);
const bindings = ref<ModelBinding[]>([]);
const routes = ref<ModelRoute[]>([]);
const platformLoading = ref(false);
const clientLoading = ref(false);
const loading = computed(() => platformLoading.value || clientLoading.value);
let appRequest = 0;
const saving = ref(false);
const testingId = ref<number>();
const discovering = ref(false);
const togglingAccount = ref(false);
const togglingModelId = ref<number>();
const providerKeyword = ref("");
const providerFilter = ref<"all" | "configured" | "pending">("all");
const modelKeyword = ref("");
const modelStatus = ref("");
const modelKind = ref("");
const modelPage = ref(1);
const modelPageSize = ref(20);
const selectedTemplate = ref<ProviderTemplate>();
const providerDialog = ref(false);
const modelDialog = ref(false);
const bindingDialog = ref(false);
const routeDialog = ref(false);
const financeDialog = ref(false);
const priceDialog = ref(false);
const financeSaving = ref(false);
const financeSyncing = ref(false);
const financeTesting = ref(false);
const priceSaving = ref(false);
const financeSummary = ref<FinanceSummary>();
const modelPrices = ref<PurchasePrice[]>([]);
const priceModel = ref<CatalogModel>();
const editingAccount = ref<ProviderAccount>();
const editingModel = ref<CatalogModel>();
const editingBinding = ref<ModelBinding>();
const modelForm = reactive({
  provider_account_id: 0,
  provider_model_id: "",
  display_name: "",
  context_length: 8192,
  speech_protocol: null as string | null,
  speech_pricing: null as SpeechPricing | null,
  supports_stream: true,
  supports_tools: true,
  supports_vision: true,
  supports_pdf: true,
  input_cost_per_million: 0,
  output_cost_per_million: 0,
  input_credits_per_1k: 1,
  output_credits_per_1k: 2,
  minimum_credits: 1,
  status: "inactive",
});
const bindingForm = reactive({
  catalog_model_id: 0,
  public_model_code: "",
  client_display_name: "",
  visible: true,
  user_selectable: true,
  is_default: false,
  input_credits_per_1k: undefined as number | undefined,
  output_credits_per_1k: undefined as number | undefined,
  order: 999,
  status: "active",
});
const routeForm = reactive({
  business_code: "chat_default",
  name: "默认聊天",
  primary_binding_id: 0,
  fallback_binding_ids: [] as number[],
  timeout_seconds: 120,
  max_output_tokens: 8192,
  generation_settings: null as GenerationSettings | null,
  allow_tools: true,
  allow_user_model: true,
  status: "active",
});
const financeForm = reactive({
  adapter_type: "manual",
  balance_warning_yuan: 100,
  settings: {} as Record<string, any>,
  status: "active",
});
const priceForm = reactive({
  catalog_model_id: 0,
  region: "",
  currency: "CNY",
  exchange_rate_to_cny: 1,
  input_cost_per_million: 0,
  cache_read_cost_per_million: 0,
  cache_write_cost_per_million: 0,
  output_cost_per_million: 0,
  reasoning_cost_per_million: 0,
  source: "manual",
  service_tier: "standard",
  billing_mode: "realtime",
  context_min: 0,
  context_max: undefined as number | undefined,
  effective_from: dayjs().format("YYYY-MM-DDTHH:mm:ssZ"),
});
const financeAdapterOptions = [
  { label: "阿里云百炼 / 千问", value: "alibaba_bss" },
  { label: "DeepSeek", value: "deepseek" },
  { label: "OpenAI 组织账单", value: "openai_admin" },
  { label: "Anthropic 组织账单", value: "anthropic_admin" },
  { label: "AWS Cost Explorer", value: "aws_cost_explorer" },
  { label: "Google Cloud 账单导入", value: "google_cloud_billing" },
  { label: "仅手工账单", value: "manual" },
];
type FinanceField = {
  key: string;
  label: string;
  secret?: boolean;
  help?: string;
  docsUrl?: string;
  placeholder?: string;
};
const alibabaAccessKeyDocs = "https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair";
const financeFieldMap: Record<string, FinanceField[]> = {
  alibaba_bss: [
    {
      key: "access_key_id",
      label: "RAM AccessKey ID",
      help: "来自专用 RAM 用户的访问密钥标识；需授予 AliyunBSSReadOnlyAccess 账单只读权限。点击图标查看获取步骤。",
      docsUrl: alibabaAccessKeyDocs,
      placeholder: "例如 LTAI5t...",
    },
    {
      key: "access_key_secret",
      label: "RAM AccessKey Secret",
      secret: true,
      help: "AccessKey Secret 仅在创建时显示一次；若已遗失，请创建新的 AccessKey。点击图标查看获取步骤。",
      docsUrl: alibabaAccessKeyDocs,
      placeholder: "仅在新建 AccessKey 时可复制",
    },
  ],
  deepseek: [{ key: "api_key", label: "财务查询 API Key", secret: true }],
  openai_admin: [{ key: "admin_key", label: "Organization Admin Key", secret: true }],
  anthropic_admin: [{ key: "admin_key", label: "Admin Key", secret: true }],
  aws_cost_explorer: [
    { key: "access_key_id", label: "只读 Access Key ID" },
    { key: "secret_access_key", label: "Secret Access Key", secret: true },
    { key: "session_token", label: "Session Token（可选）", secret: true },
    { key: "region", label: "区域（默认 us-east-1）" },
  ],
};
const financeFields = computed(() => financeFieldMap[financeForm.adapter_type] || []);
const needsExchangeRate = computed(() =>
  ["openai_admin", "anthropic_admin", "aws_cost_explorer"].includes(financeForm.adapter_type)
);
const selectedAccount = computed(() =>
  selectedTemplate.value
    ? accounts.value.find((item) => item.template_id === selectedTemplate.value?.id)
    : undefined
);
const balanceCapabilityText = computed(() => {
  if (!financeSummary.value?.profile) return "未配置财务连接";
  return financeSummary.value.profile.capabilities.balance
    ? "尚未同步余额"
    : "供应商未提供余额接口";
});
const filteredTemplates = computed(() =>
  sortProviderTemplates(templates.value, accountFor).filter((item) => {
    const account = accountFor(item);
    return (
      (!providerKeyword.value ||
        `${item.name}${item.code}`.toLowerCase().includes(providerKeyword.value.toLowerCase())) &&
      (providerFilter.value === "all" ||
        (providerFilter.value === "configured" ? !!account : !account))
    );
  })
);
const selectedModels = computed(() =>
  selectedAccount.value
    ? sortCatalogModels(
        models.value.filter((item) => item.provider_account_id === selectedAccount.value?.id),
        selectedTemplate.value?.recommended_model
      )
    : []
);
const filteredModels = computed(() =>
  selectedModels.value.filter(
    (item) =>
      (!modelKeyword.value ||
        `${item.display_name}${item.provider_model_id}`
          .toLowerCase()
          .includes(modelKeyword.value.toLowerCase())) &&
      (!modelStatus.value || item.status === modelStatus.value) &&
      (!modelKind.value ||
        (modelKind.value === "chat"
          ? isChatGatewayCompatible(item.provider_model_id)
          : !isChatGatewayCompatible(item.provider_model_id)))
  )
);
const pagedModels = computed(() => {
  const start = (modelPage.value - 1) * modelPageSize.value;
  return filteredModels.value.slice(start, start + modelPageSize.value);
});
const activeModels = computed(() =>
  models.value.filter(
    (item) =>
      item.status === "active" &&
      !item.speech_protocol &&
      isChatGatewayCompatible(item.provider_model_id) &&
      accounts.value.some(
        (account) =>
          account.id === item.provider_account_id &&
          account.status === "active" &&
          account.connection_status === "healthy"
      )
  )
);
const activeBindings = computed(() => bindings.value.filter((item) => item.status === "active"));
function accountFor(template: ProviderTemplate) {
  return accounts.value.find((item) => item.template_id === template.id);
}
function hasVerifiedCost(model: CatalogModel) {
  return Number(model.input_cost_per_million) > 0 && Number(model.output_cost_per_million) > 0;
}
function maskSummary(account: ProviderAccount) {
  return Object.values(account.masked_summary).filter(Boolean).join(" · ") || "已安全保存";
}
const formatDate = (value?: string) => (value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—");
const formatCost = (value?: number) =>
  Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
const financeMoney = (value?: number, digits = 2) =>
  value === undefined || value === null
    ? "—"
    : `¥${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const signedMoney = (value?: number) =>
  value === undefined || value === null ? "—" : `${value > 0 ? "+" : ""}${financeMoney(value, 4)}`;
function bindingName(id: number) {
  return bindings.value.find((item) => item.id === id)?.client_display_name || `#${id}`;
}
function businessName(code: string) {
  return (
    (
      {
        chat_default: "默认聊天",
        document_intelligence: "文档理解",
        semantic_review: "语义审核",
      } as Record<string, string>
    )[code] || code
  );
}
function businessIcon(code: string) {
  return (
    (
      {
        chat_default: "ri:chat-3-line",
        document_intelligence: "ri:file-search-line",
        semantic_review: "ri:shield-check-line",
      } as Record<string, string>
    )[code] || "ri:route-line"
  );
}
async function loadPlatform() {
  platformLoading.value = true;
  try {
    const [a, b, c] = await Promise.all([
      ModelGatewayAPI.templates(),
      ModelGatewayAPI.accounts(),
      ModelGatewayAPI.models(),
    ]);
    templates.value = a.data.data || [];
    accounts.value = b.data.data || [];
    models.value = c.data.data || [];
    const orderedTemplates = sortProviderTemplates(templates.value, accountFor);
    if (!selectedTemplate.value) selectedTemplate.value = orderedTemplates[0];
    else
      selectedTemplate.value =
        templates.value.find((item) => item.id === selectedTemplate.value?.id) ||
        orderedTemplates[0];
  } catch {
    // 请求层统一反馈错误，保留当前界面状态。
  } finally {
    platformLoading.value = false;
  }
}
async function loadApp() {
  const request = ++appRequest;
  bindings.value = [];
  routes.value = [];
  if (!currentApp.value) {
    clientLoading.value = false;
    return;
  }
  clientLoading.value = true;
  try {
    const [a, b] = await Promise.all([ModelGatewayAPI.bindings(), ModelGatewayAPI.routes()]);
    if (request !== appRequest) return;
    bindings.value = a.data.data || [];
    routes.value = b.data.data || [];
  } catch {
    // 请求层统一反馈错误，避免异步生命周期错误冒泡到组件边界。
  } finally {
    if (request === appRequest) clientLoading.value = false;
  }
}
async function loadFinance() {
  if (!selectedAccount.value?.id) {
    financeSummary.value = undefined;
    return;
  }
  try {
    const response = await ModelGatewayAPI.financeSummary(Number(selectedAccount.value.id));
    financeSummary.value = response.data.data;
  } catch {
    financeSummary.value = undefined;
  }
}
function inferredFinanceAdapter() {
  const code = selectedTemplate.value?.code;
  if (code === "qwen") return "alibaba_bss";
  if (code === "deepseek") return "deepseek";
  if (code === "openai") return "openai_admin";
  if (code === "anthropic") return "anthropic_admin";
  if (code === "bedrock") return "aws_cost_explorer";
  if (code === "vertex") return "google_cloud_billing";
  return "manual";
}
function resetFinanceSettings() {
  financeForm.settings = {};
  if (needsExchangeRate.value) financeForm.settings.exchange_rate_to_cny = 7;
}
function openFinance() {
  financeForm.adapter_type =
    financeSummary.value?.profile?.adapter_type || inferredFinanceAdapter();
  financeForm.balance_warning_yuan = financeSummary.value?.profile?.balance_warning_yuan || 100;
  resetFinanceSettings();
  financeDialog.value = true;
}
async function saveFinance() {
  if (!selectedAccount.value?.id) return;
  financeSaving.value = true;
  try {
    const settings = Object.fromEntries(
      Object.entries(financeForm.settings).filter(
        ([, value]) => value !== "" && value !== undefined
      )
    );
    await ModelGatewayAPI.saveFinance(Number(selectedAccount.value.id), {
      adapter_type: financeForm.adapter_type,
      balance_warning_yuan: financeForm.balance_warning_yuan,
      status: financeForm.status,
      settings,
    });
    financeDialog.value = false;
    await loadFinance();
    ElMessage.success("财务连接已安全保存");
  } catch {
    // 请求层已展示错误。
  } finally {
    financeSaving.value = false;
  }
}
async function syncFinance() {
  if (!selectedAccount.value?.id) return;
  financeSyncing.value = true;
  try {
    const response = await ModelGatewayAPI.syncFinance(Number(selectedAccount.value.id));
    financeSummary.value = response.data.data;
    if (financeSummary.value.profile?.last_error) {
      ElMessage.warning("同步失败，已保留上次成功的余额与账单数据");
    } else {
      ElMessage.success("余额与账单同步完成");
    }
  } catch {
    // 请求层已展示错误。
  } finally {
    financeSyncing.value = false;
  }
}
async function testFinance() {
  if (!selectedAccount.value?.id) return;
  financeTesting.value = true;
  try {
    const response = await ModelGatewayAPI.testFinance(Number(selectedAccount.value.id));
    await loadFinance();
    if (response.data.data.last_error) {
      ElMessage.warning(`连接测试失败：${response.data.data.last_error}`);
    } else {
      ElMessage.success("财务连接测试通过");
    }
  } catch {
    // 请求层已展示错误。
  } finally {
    financeTesting.value = false;
  }
}
async function openPrice(model: CatalogModel) {
  if (!selectedAccount.value?.id || !model.id) return;
  priceModel.value = model;
  Object.assign(priceForm, {
    catalog_model_id: Number(model.id),
    region: "",
    service_tier: "standard",
    billing_mode: "realtime",
    context_min: 0,
    context_max: undefined,
    currency: "CNY",
    exchange_rate_to_cny: 1,
    input_cost_per_million: Number(model.input_cost_per_million || 0),
    cache_read_cost_per_million: Number(model.input_cost_per_million || 0),
    cache_write_cost_per_million: Number(model.input_cost_per_million || 0),
    output_cost_per_million: Number(model.output_cost_per_million || 0),
    reasoning_cost_per_million: Number(model.output_cost_per_million || 0),
    effective_from: dayjs().format("YYYY-MM-DDTHH:mm:ssZ"),
  });
  try {
    const response = await ModelGatewayAPI.prices(Number(selectedAccount.value.id));
    modelPrices.value = (response.data.data || []).filter(
      (item) => item.catalog_model_id === model.id
    );
    const basePrice = modelPrices.value.find(
      (item) => item.status === "active" && item.context_min === 0
    );
    if (basePrice) {
      Object.assign(priceForm, {
        region: basePrice.region || "",
        service_tier: basePrice.service_tier,
        billing_mode: basePrice.billing_mode,
        context_min: basePrice.context_min,
        context_max: basePrice.context_max,
        currency: basePrice.currency,
        exchange_rate_to_cny: Number(basePrice.exchange_rate_to_cny),
        input_cost_per_million: Number(basePrice.input_cost_per_million),
        cache_read_cost_per_million: Number(basePrice.cache_read_cost_per_million),
        cache_write_cost_per_million: Number(basePrice.cache_write_cost_per_million),
        output_cost_per_million: Number(basePrice.output_cost_per_million),
        reasoning_cost_per_million: Number(basePrice.reasoning_cost_per_million),
      });
    }
    priceDialog.value = true;
  } catch {
    // 请求层已展示错误。
  }
}
async function savePrice() {
  if (!selectedAccount.value?.id) return;
  priceSaving.value = true;
  try {
    const modelId = priceModel.value?.id;
    await ModelGatewayAPI.createPrice(Number(selectedAccount.value.id), { ...priceForm });
    await loadPlatform();
    const refreshed = models.value.find((item) => item.id === modelId);
    if (refreshed) await openPrice(refreshed);
    ElMessage.success("新价格版本已生效，历史请求成本不会改变");
  } catch {
    // 请求层已展示错误。
  } finally {
    priceSaving.value = false;
  }
}
function openProvider(row?: ProviderAccount) {
  if (!selectedTemplate.value?.adapter_ready) return ElMessage.warning("该供应商适配器尚未启用");
  editingAccount.value = row;
  providerDialog.value = true;
}
function openModel(row?: CatalogModel) {
  editingModel.value = row;
  Object.assign(
    modelForm,
    row || {
      provider_account_id: selectedAccount.value?.id || accounts.value[0]?.id || 0,
      provider_model_id: "",
      display_name: "",
      context_length: 8192,
      speech_protocol: null as string | null,
      speech_pricing: null as SpeechPricing | null,
      supports_stream: true,
      supports_tools: true,
      supports_vision: true,
      supports_pdf: true,
      input_cost_per_million: 0,
      output_cost_per_million: 0,
      input_credits_per_1k: 1,
      output_credits_per_1k: 2,
      minimum_credits: 1,
      status: "inactive",
    }
  );
  modelDialog.value = true;
}
function openBinding(row?: ModelBinding) {
  editingBinding.value = row;
  Object.assign(
    bindingForm,
    row || {
      catalog_model_id: activeModels.value[0]?.id || 0,
      public_model_code: "",
      client_display_name: "",
      visible: true,
      user_selectable: true,
      is_default: false,
      input_credits_per_1k: undefined,
      output_credits_per_1k: undefined,
      order: 999,
      status: "active",
    }
  );
  bindingDialog.value = true;
}
function openRoute(row?: ModelRoute) {
  Object.assign(
    routeForm,
    row || {
      business_code: "chat_default",
      name: "默认聊天",
      primary_binding_id: activeBindings.value[0]?.id || 0,
      fallback_binding_ids: [],
      timeout_seconds: 120,
      max_output_tokens: 8192,
      allow_tools: true,
      allow_user_model: true,
      status: "active",
    }
  );
  routeForm.fallback_binding_ids = [...routeForm.fallback_binding_ids];
  routeForm.generation_settings = row?.generation_settings ? { ...row.generation_settings } : null;
  routeDialog.value = true;
}
async function saveAccount(data: Record<string, unknown>) {
  saving.value = true;
  try {
    if (editingAccount.value?.id)
      await ModelGatewayAPI.updateAccount(editingAccount.value.id, {
        name: data.name,
        endpoint: data.endpoint,
        settings: data.settings,
        timeout_seconds: data.timeout_seconds,
        retry_count: data.retry_count,
      });
    else await ModelGatewayAPI.createAccount(data);
    providerDialog.value = false;
    await loadPlatform();
  } catch {
    // 请求层已展示错误。
  } finally {
    saving.value = false;
  }
}
async function saveModel() {
  if (!modelForm.provider_account_id || !modelForm.provider_model_id || !modelForm.display_name)
    return ElMessage.warning("请完整填写模型");
  saving.value = true;
  try {
    if (editingModel.value?.id) {
      const payload: Record<string, unknown> = { ...modelForm };
      delete payload.provider_account_id;
      delete payload.provider_model_id;
      delete payload.status;
      await ModelGatewayAPI.updateModel(editingModel.value.id, payload);
    } else await ModelGatewayAPI.createModel({ ...modelForm });
    modelDialog.value = false;
    await loadPlatform();
  } catch {
    // 请求层已展示错误。
  } finally {
    saving.value = false;
  }
}
async function saveBinding() {
  if (
    !bindingForm.catalog_model_id ||
    !bindingForm.public_model_code ||
    !bindingForm.client_display_name
  )
    return ElMessage.warning("请完整填写客户端授权");
  saving.value = true;
  try {
    if (editingBinding.value?.id) {
      const payload: Record<string, unknown> = { ...bindingForm };
      delete payload.catalog_model_id;
      delete payload.public_model_code;
      delete payload.status;
      await ModelGatewayAPI.updateBinding(editingBinding.value.id, payload);
    } else await ModelGatewayAPI.createBinding({ ...bindingForm });
    bindingDialog.value = false;
    await loadApp();
  } catch {
    // 请求层已展示错误。
  } finally {
    saving.value = false;
  }
}
async function saveRoute() {
  if (!routeForm.primary_binding_id) return ElMessage.warning("请选择主模型");
  saving.value = true;
  try {
    await ModelGatewayAPI.saveRoute({ ...routeForm });
    routeDialog.value = false;
    await loadApp();
  } catch {
    // 请求层已展示错误。
  } finally {
    saving.value = false;
  }
}
async function testAndDiscover(account: ProviderAccount) {
  if (!account.id) return;
  testingId.value = account.id;
  discovering.value = true;
  try {
    const response = await ModelGatewayAPI.discoverModels(account.id);
    const rows = response.data.data || [];
    const priced = rows.filter((item) => item.price_matched).length;
    ElMessage.success(
      priced
        ? "连接成功，已同步 " + rows.length + " 个模型，自动匹配 " + priced + " 个官方价格"
        : "连接成功，已同步 " + rows.length + " 个模型"
    );
    await loadPlatform();
  } catch {
    // 请求层已展示 HTTP 或供应商错误。
  } finally {
    testingId.value = undefined;
    discovering.value = false;
  }
}
async function discoverSelected() {
  if (!selectedAccount.value?.id || discovering.value) return;
  discovering.value = true;
  try {
    const response = await ModelGatewayAPI.discoverModels(selectedAccount.value.id);
    const rows = response.data.data || [];
    const priced = rows.filter((item) => item.price_matched).length;
    ElMessage.success(
      priced
        ? "目录已刷新，" + priced + " 个模型已匹配官方价格"
        : "目录已刷新，未确认价格的模型需人工配置后启用"
    );
    await loadPlatform();
  } catch {
    // 请求层已展示错误。
  } finally {
    discovering.value = false;
  }
}
async function toggleAccount(id: number, status: ProviderAccount["status"]) {
  if (togglingAccount.value) return;
  togglingAccount.value = true;
  const nextStatus = status === "active" ? "inactive" : "active";
  try {
    await ModelGatewayAPI.setAccountStatus(id, nextStatus);
    ElMessage.success(nextStatus === "active" ? "供应商账号已启用" : "供应商账号已停用");
    await loadPlatform();
  } catch {
    // 请求层已展示错误。
  } finally {
    togglingAccount.value = false;
  }
}
async function toggleModel(id: number, active: boolean) {
  if (togglingModelId.value !== undefined) return;
  const model = models.value.find((item) => item.id === id);
  if (!model) return;
  if (
    active &&
    !isChatGatewayCompatible(model.provider_model_id) &&
    !(model.speech_protocol || isSpeechInputModel(model.provider_model_id))
  ) {
    ElMessage.warning("该模型尚未配置可用的语音识别接口，请在模型编辑中完成配置");
    return;
  }
  if (
    active &&
    !(model.speech_protocol || isSpeechInputModel(model.provider_model_id)) &&
    !hasVerifiedCost(model)
  ) {
    ElMessage.warning("请先确认并保存采购价格，再启用模型");
    await openPrice(model);
    return;
  }
  if (
    active &&
    (model.speech_protocol || isSpeechInputModel(model.provider_model_id)) &&
    !model.speech_pricing
  ) {
    ElMessage.warning("请先填写语音采购价，再启用模型");
    openModel(model);
    return;
  }
  if (active && selectedAccount.value?.connection_status !== "healthy") {
    ElMessage.warning("请先完成供应商连接测试，再启用模型");
    return;
  }
  const activatesProvider = active && selectedAccount.value?.status !== "active";
  togglingModelId.value = id;
  try {
    await ModelGatewayAPI.setModelStatus(id, active ? "active" : "inactive");
    ElMessage.success(
      active ? (activatesProvider ? "供应商账号与模型已一并启用" : "模型已启用") : "模型已停用"
    );
    await loadPlatform();
  } catch {
    // 请求层已展示错误。
  } finally {
    togglingModelId.value = undefined;
  }
}
async function toggleBinding(id: number, active: boolean) {
  try {
    await ModelGatewayAPI.setBindingStatus(id, active ? "active" : "inactive");
    ElMessage.success(active ? "客户端模型已启用" : "客户端模型已停用");
    await loadApp();
  } catch {
    // 请求层已展示错误。
  }
}
watch([modelKeyword, modelStatus, modelKind, modelPageSize], () => {
  modelPage.value = 1;
});
watch(
  () => currentApp.value?.id,
  () => {
    if (workspace.value === "client") void loadApp();
  },
  { immediate: true }
);
watch(
  () => selectedAccount.value?.id,
  () => {
    modelPage.value = 1;
    if (workspace.value === "platform") void loadFinance();
  },
  { immediate: true }
);
watch(workspace, (value) => {
  if (value === "client") void loadApp();
});
watch(
  [providerDialog, modelDialog, bindingDialog, routeDialog, financeDialog, priceDialog],
  (values) => clientAppStore.markDirty("model-management-editor", values.some(Boolean))
);
onUnmounted(() => clientAppStore.markDirty("model-management-editor", false));
onMounted(loadPlatform);
</script>

<style scoped>
.model-workspace {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: var(--app-bg);
}

.platform-layout {
  display: grid;
  flex: 1;
  grid-template-columns: 252px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
}

.provider-panel,
.provider-detail,
.client-layout {
  min-height: 0;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  box-shadow: var(--el-box-shadow-lighter);
}

.provider-panel {
  display: flex;
  flex-direction: column;
  padding: 14px;
}

.aside-title,
.section-head,
.model-tools,
.provider-hero {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.aside-title > div,
.section-head > div,
.model-tools > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.aside-title small,
.section-head span,
.model-tools span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.provider-filter {
  display: flex;
  gap: 5px;
  padding: 11px 0;
}

.provider-filter button {
  padding: 5px 9px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 7px;
}

.provider-filter button.active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.provider-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-height: 0;
  overflow: auto;
}

.provider-item {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 8px;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 9px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
}

.provider-item:hover {
  background: var(--el-fill-color-lighter);
}

.provider-item.active {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
}

.provider-logo,
.hero-logo {
  display: grid;
  place-items: center;
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}

.provider-logo {
  width: 38px;
  height: 38px;
  font-size: 19px;
  border-radius: 9px;
}

.provider-item > span:nth-child(2) {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.provider-item small {
  margin-top: 3px;
  color: var(--el-text-color-secondary);
}

.provider-item i {
  width: 7px;
  height: 7px;
  background: var(--el-border-color);
  border-radius: 50%;
}

.provider-item i.healthy {
  background: var(--el-color-success);
}

.provider-detail {
  padding: 20px;
  overflow: auto;
}

.provider-hero > div:nth-child(2) {
  flex: 1;
  min-width: 0;
}

.provider-hero > div > div {
  display: flex;
  gap: 8px;
  align-items: center;
}

.provider-hero h2 {
  margin: 0;
  font-size: 20px;
}

.provider-hero p {
  margin: 7px 0;
  color: var(--el-text-color-regular);
}

.provider-hero > div > span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.hero-logo {
  width: 58px;
  height: 58px;
  font-size: 28px;
  border-radius: 14px;
}

.hero-actions {
  display: flex;
  gap: 8px;
}

.connection-card {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  gap: 1px;
  margin: 18px 0;
  overflow: hidden;
  background: var(--el-border-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.finance-card {
  padding: 16px;
  margin-bottom: 18px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.finance-card .section-head {
  flex-wrap: wrap;
}

.finance-actions {
  display: flex;
  flex: 0 0 auto;
  flex-direction: row !important;
  flex-wrap: nowrap;
  gap: 8px;
  white-space: nowrap;
}

.finance-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 14px 0 10px;
  overflow: hidden;
  background: var(--el-border-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 9px;
}

.finance-metrics > div {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 13px;
  background: var(--el-bg-color);
}

.finance-metrics span,
.finance-metrics small,
.price-history small {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.finance-metrics strong {
  font-size: 17px;
  color: var(--el-text-color-primary);
}

.resource-packages {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin: 2px 0 10px;
}

.resource-packages__label {
  flex: 0 0 auto;
  padding-top: 3px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.resource-packages__list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.resource-packages > small {
  padding-top: 3px;
  color: var(--el-text-color-placeholder);
}

.finance-form {
  margin-top: 16px;
}

.price-history {
  display: grid;
  gap: 7px;
  max-height: 220px;
  overflow: auto;
}

.price-history__item {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) repeat(4, minmax(90px, auto)) auto;
  gap: 14px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.model-table-wrap .cost-column {
  width: 94px;
  min-width: 94px;
  white-space: nowrap;
}

.model-table-wrap .cost-column small {
  font-size: 10px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}

.model-table-wrap .cost-value-cell {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.model-table-wrap .cost-value-cell strong {
  font-size: 13px;
  font-weight: 650;
}

.finance-field-label {
  display: inline-flex;
  gap: 5px;
  align-items: center;
}

.finance-field-help {
  display: inline-flex;
  align-items: center;
  color: var(--el-color-warning);
}

.finance-access-guide {
  grid-column: 1 / -1;
  padding: 10px 12px;
  margin: -2px 0 16px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.finance-access-guide a {
  margin-left: 4px;
  color: var(--el-color-primary);
}

.price-history__item > span:first-child {
  display: grid;
  gap: 3px;
}

.connection-card > div {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 13px;
  background: var(--el-fill-color-extra-light);
}

.connection-card span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.connection-card strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-tools {
  padding: 4px 0 12px;
}

.model-tools > div:last-child {
  display: flex;
  gap: 8px;
}

.model-tools .el-input {
  width: 180px;
}

.model-tools .el-select {
  width: 118px;
}

.model-table-wrap {
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.model-table-wrap table {
  width: 100%;
  border-collapse: collapse;
}

.model-table-wrap th,
.model-table-wrap td {
  padding: 12px;
  font-size: 13px;
  text-align: left;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.model-table-wrap th {
  font-weight: 500;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}

.model-table-wrap td strong,
.model-table-wrap td small {
  display: block;
  margin: 3px 0;
}

.model-table-wrap small {
  color: var(--el-text-color-secondary);
}

.capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.model-pagination {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 720px;
  padding: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-extra-light);
}

.client-layout {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  overflow: auto;
}

.client-models,
.route-section {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  min-height: 0;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.client-models > .section-head,
.route-section > .section-head {
  flex-shrink: 0;
}

.section-head > .client-model-actions {
  flex-flow: row wrap;
  gap: 8px;
}

.client-model-actions .el-button + .el-button {
  margin-left: 0;
}

.binding-grid {
  display: grid;
  flex: 1;
  grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
  gap: 10px;
  align-content: start;
  min-height: 0;
  margin-top: 14px;
  overflow: auto;
}

.binding-grid article {
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.binding-grid article > div:first-child {
  display: flex;
  gap: 9px;
  align-items: center;
}

.binding-grid article > div:first-child > span:last-child {
  display: flex;
  flex-direction: column;
}

.binding-grid small {
  color: var(--el-text-color-secondary);
}

.model-mark,
.route-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 9px;
}

.binding-tags {
  display: flex;
  gap: 5px;
}

.card-actions {
  text-align: right;
}

.route-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  margin-top: 14px;
  overflow: auto;
}

.route-list article {
  display: grid;
  grid-template-columns: 40px 160px minmax(0, 1fr) auto auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.route-list article > div:nth-child(2) {
  display: flex;
  flex-direction: column;
}

.route-list small {
  color: var(--el-text-color-secondary);
}

.route-flow {
  display: flex;
  gap: 7px;
  align-items: center;
  min-width: 0;
}

.route-flow span {
  color: var(--el-text-color-secondary);
}

.empty-client {
  display: grid;
  place-items: center;
  height: 100%;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.form-grid .el-input-number,
.form-grid .el-select {
  width: 100%;
}

.context-range {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  width: 100%;
  color: var(--el-text-color-secondary);
}

.feature-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
}
@media (width<=1300px) {
  .connection-card {
    grid-template-columns: 1fr 1fr;
  }

  .binding-grid {
    grid-template-columns: 1fr 1fr;
  }

  .finance-metrics {
    grid-template-columns: 1fr 1fr;
  }
}
@media (width<=850px) {
  .platform-layout {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .provider-panel {
    min-height: 340px;
  }

  .provider-detail {
    overflow: visible;
  }

  .provider-hero {
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .hero-actions {
    flex-wrap: wrap;
    width: 100%;
  }

  .connection-card,
  .binding-grid,
  .finance-metrics {
    grid-template-columns: 1fr;
  }

  .model-tools {
    flex-direction: column;
    align-items: flex-start;
  }

  .model-tools > div:last-child {
    flex-wrap: wrap;
    width: 100%;
  }

  .route-list article {
    grid-template-columns: 40px minmax(0, 1fr) auto;
  }

  .route-flow {
    grid-column: 2/-1;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}

.provider-search {
  display: flex;
  gap: 8px;
  align-items: center;
}

.provider-search .el-input {
  flex: 1;
  min-width: 0;
}

.provider-search .el-button {
  padding: 9px;
}

.field-help {
  margin: 6px 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.provider-item {
  color: var(--el-text-color-primary);
}

.provider-item strong {
  font-size: 14px;
}

.provider-item small {
  font-size: 12px;
}

.provider-item:focus-visible,
.provider-filter button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

.provider-hero {
  flex-wrap: wrap;
  padding-bottom: 4px;
}

.hero-actions {
  flex-wrap: wrap;
}

.hero-actions .el-button + .el-button,
.finance-actions .el-button + .el-button,
.model-tools .el-button + .el-button {
  margin-left: 0;
}

.connection-card strong {
  font-size: 13px;
  font-weight: 500;
}

.client-layout {
  padding: 0;
  background: transparent;
  border: 0;
  box-shadow: none;
}

.client-models,
.route-section {
  padding: 20px;
  background: var(--el-bg-color);
}

.client-layout > .el-alert,
.setup-guide {
  flex-shrink: 0;
}

.setup-guide {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  padding: 18px 20px;
  margin-bottom: 0;
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-8);
  border-radius: 12px;
}

.setup-guide div {
  display: grid;
  gap: 6px;
}

.setup-guide b {
  font-size: 14px;
  color: var(--el-color-primary);
}

.setup-guide span {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.binding-grid:has(> .el-empty) {
  align-content: stretch;
}

.binding-grid > .el-empty {
  grid-column: 1 / -1;
}

.route-list > .el-empty {
  flex: 1;
}

.binding-tags,
.route-flow {
  flex-wrap: wrap;
}

.binding-grid strong,
.binding-grid small,
.route-flow b {
  overflow-wrap: anywhere;
}

.section-head {
  flex-wrap: wrap;
}
@media (width <= 1100px) {
  .model-tools {
    flex-wrap: wrap;
  }

  .model-tools > div:last-child {
    flex-wrap: wrap;
  }

  .finance-card .section-head {
    align-items: flex-start;
  }
}
@media (width <= 850px) {
  .setup-guide {
    grid-template-columns: 1fr;
  }

  .provider-panel {
    min-height: 240px;
    max-height: 320px;
  }

  .route-list article {
    grid-template-columns: 40px minmax(0, 1fr);
  }

  .connection-card strong {
    overflow-wrap: anywhere;
    white-space: normal;
  }
}
</style>
