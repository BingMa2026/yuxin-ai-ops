import { request } from "@utils";

export type ServiceMode = "credits_only" | "duration_only" | "user_choice";
export type BillingMode = "credits" | "duration";
export const billingModeLabel = (mode?: string | null) =>
  mode === "credits" ? "含 token 费用" : mode === "duration" ? "token 自费" : "未选择";
export const serviceModeLabel = (mode?: string) =>
  mode === "user_choice"
    ? "均支持"
    : billingModeLabel(
        mode === "credits_only" ? "credits" : mode === "duration_only" ? "duration" : null
      );

export const modeSwitchLabel = (status?: string) =>
  ({
    pending_payment: "待支付",
    processing: "处理中",
    completed: "已生效",
    requires_confirmation: "待核对",
    failed: "处理失败",
    cancelled: "已取消",
  })[status || ""] || "—";

export type ClientAppStatus = "draft" | "active" | "inactive";

export interface ClientAppInfo extends BaseType {
  code: string;
  name: string;
  logo?: string;
  client_version?: string;
  status: ClientAppStatus;
  service_mode?: ServiceMode;
  platform_model_enabled?: boolean;
  model_policy_version?: number;
  registration_enabled: boolean;
  order: number;
  description?: string;
  can_switch?: boolean;
  is_current?: boolean;
}

export interface ClientAppForm {
  name: string;
  code?: string;
  logo?: string;
  client_version?: string;
  status?: ClientAppStatus;
  service_mode?: ServiceMode;
  platform_model_enabled?: boolean;
  expected_policy_version?: number;
  registration_enabled?: boolean;
  order?: number;
  description?: string;
}

export interface ClientAppQuery extends PageQuery {
  name?: string;
  code?: string;
  status?: ClientAppStatus;
}

export interface ClientAppStaffOption {
  id: number;
  username: string;
  name: string;
  selected: boolean;
}

export type ClientReleaseStatus = "draft" | "published" | "withdrawn";
export interface ClientReleaseArtifact extends BaseType {
  release_id: number;
  artifact_type: "installer" | "blockmap";
  source_type: "upload" | "external";
  storage_source_id?: number;
  storage_path?: string;
  external_url?: string;
  file_name: string;
  file_size: number;
  sha512?: string;
  signature_verified: boolean;
}
export interface ClientRelease extends BaseType {
  app_id: number;
  platform: "windows";
  arch: "x64";
  channel: "stable" | "test";
  version: string;
  release_notes: string;
  min_supported_version?: string;
  force_update: boolean;
  status: ClientReleaseStatus;
  published_at?: string;
  artifacts: ClientReleaseArtifact[];
}

const ClientAppAPI = {
  list(query: ClientAppQuery) {
    return request<ApiResponse<PageResult<ClientAppInfo>>>({
      url: "/operations/client-apps/list",
      method: "get",
      params: query,
    });
  },
  switchable() {
    return request<ApiResponse<ClientAppInfo[]>>({
      url: "/operations/client-apps/switchable",
      method: "get",
    });
  },
  create(body: ClientAppForm & { code: string }) {
    return request<ApiResponse<ClientAppInfo>>({
      url: "/operations/client-apps",
      method: "post",
      data: body,
    });
  },
  update(id: number, body: ClientAppForm) {
    return request<ApiResponse<ClientAppInfo>>({
      url: `/operations/client-apps/${id}`,
      method: "put",
      data: body,
    });
  },
  detail(id: number) {
    return request<ApiResponse<ClientAppInfo>>({
      url: `/operations/client-apps/${id}`,
      method: "get",
    });
  },
  releases(id: number) {
    return request<ApiResponse<ClientRelease[]>>({
      url: `/operations/client-apps/${id}/releases`,
      method: "get",
    });
  },
  createRelease(id: number, data: Record<string, unknown>) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases`,
      method: "post",
      data,
    });
  },
  updateRelease(id: number, releaseId: number, data: Record<string, unknown>) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases/${releaseId}`,
      method: "put",
      data,
    });
  },
  saveExternalArtifact(id: number, releaseId: number, data: Record<string, unknown>) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases/${releaseId}/external-artifact`,
      method: "put",
      data,
    });
  },
  uploadArtifact(
    id: number,
    releaseId: number,
    data: FormData,
    onProgress?: (percent: number) => void
  ) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases/${releaseId}/upload`,
      method: "post",
      data,
      timeout: 0,
      onUploadProgress: (event) => {
        if (event.total) onProgress?.(Math.round((event.loaded / event.total) * 100));
      },
    });
  },
  publishRelease(id: number, releaseId: number) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases/${releaseId}/publish`,
      method: "post",
    });
  },
  withdrawRelease(id: number, releaseId: number) {
    return request<ApiResponse<ClientRelease>>({
      url: `/operations/client-apps/${id}/releases/${releaseId}/withdraw`,
      method: "post",
    });
  },
  setStaff(id: number, staffIds: number[]) {
    return request<ApiResponse>({
      url: `/operations/client-apps/${id}/staff`,
      method: "put",
      data: { staff_ids: staffIds },
    });
  },
  staff(id: number) {
    return request<ApiResponse<ClientAppStaffOption[]>>({
      url: `/operations/client-apps/${id}/staff`,
      method: "get",
    });
  },
};

export default ClientAppAPI;
