import { request, type ExtendedRequestConfig } from "@utils";

export interface Agreement {
  id: number;
  app_id: number;
  code: string;
  title: string;
  content: string;
  change_summary: string;
  status: "draft" | "published" | "archived";
  current_version: number;
  has_draft: boolean;
  revision: number;
  updated_time: string;
  updated_by: number | null;
}
export type DraftInput = Pick<
  Agreement,
  "code" | "title" | "content" | "change_summary" | "revision"
>;
export interface AgreementVersion {
  id: number;
  version: number;
  title: string;
  content: string;
  change_summary: string;
  published_at: string;
  published_by: number | null;
}
export interface AgreementScene {
  id: number;
  app_id: number;
  code: string;
  name: string;
  agreement_ids: number[];
  require_acceptance: boolean;
  revision: number;
  updated_time: string;
}
export type SceneInput = Omit<AgreementScene, "id" | "app_id" | "updated_time">;
export interface AgreementQuery {
  page_no: number;
  page_size: number;
  keyword?: string;
  status?: string;
  has_draft?: boolean;
}
const base = "/operations/agreements";
const quiet: ExtendedRequestConfig = { showSuccessMessage: false };
const get = <T>(path: string, params?: object) =>
  request<ApiResponse<T>>({ url: `${base}${path}`, method: "get", params });
const post = <T>(path: string, data?: object) =>
  request<ApiResponse<T>>({ url: `${base}${path}`, method: "post", data });
export default {
  list: (params: AgreementQuery) => get<PageResult<Agreement>>("", params),
  detail: (id: number) => get<Agreement>(`/${id}`),
  save: (data: DraftInput, id?: number) =>
    request<ApiResponse<Agreement>>({
      url: id ? `${base}/${id}` : base,
      method: id ? "put" : "post",
      data,
      ...quiet,
    }),
  publish: (id: number, revision: number) => post<Agreement>(`/${id}/publish`, { revision }),
  archive: (id: number, revision: number) => post<void>(`/${id}/archive`, { revision }),
  unarchive: (id: number, revision: number) => post<Agreement>(`/${id}/unarchive`, { revision }),
  remove: (id: number, revision: number) =>
    request<ApiResponse<void>>({ url: `${base}/${id}`, method: "delete", params: { revision } }),
  versions: (id: number) => get<AgreementVersion[]>(`/${id}/versions`),
  restore: (id: number, version: number, revision: number) =>
    post<Agreement>(`/${id}/versions/${version}/restore`, { revision }),
  scenes: (params: AgreementQuery) => get<PageResult<AgreementScene>>("/scenes", params),
  saveScene: (data: SceneInput, id?: number) =>
    request<ApiResponse<AgreementScene>>({
      url: id ? `${base}/scenes/${id}` : `${base}/scenes`,
      method: id ? "put" : "post",
      data,
    }),
  removeScene: (id: number, revision: number) =>
    request<ApiResponse<void>>({
      url: `${base}/scenes/${id}`,
      method: "delete",
      params: { revision },
    }),
};
