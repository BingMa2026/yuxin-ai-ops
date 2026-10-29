import { request } from "@utils";

const API_PATH = "/system/module";

export type WorkspaceModuleStatus = "active" | "coming_soon" | "disabled";

export interface WorkspaceModule extends BaseType {
  code: string;
  name: string;
  icon?: string;
  description?: string;
  accent: string;
  order: number;
  status: WorkspaceModuleStatus;
  menu_count: number;
  menu_items: Array<{
    name: string;
    icon?: string;
    route_path?: string;
  }>;
}

export interface WorkspaceModuleForm extends BaseFormType {
  code: string;
  name: string;
  icon?: string;
  description?: string;
  accent: string;
  order: number;
  status: WorkspaceModuleStatus;
}

export interface WorkspaceModuleQuery extends BaseQueryParams {
  code?: string;
  name?: string;
  status?: WorkspaceModuleStatus;
}

const WorkspaceModuleAPI = {
  available() {
    return request<ApiResponse<WorkspaceModule[]>>({
      url: `${API_PATH}/available`,
      method: "get",
    });
  },
  list(query?: WorkspaceModuleQuery) {
    return request<ApiResponse<WorkspaceModule[]>>({
      url: `${API_PATH}/list`,
      method: "get",
      params: query,
    });
  },
  detail(id: number) {
    return request<ApiResponse<WorkspaceModule>>({
      url: `${API_PATH}/detail/${id}`,
      method: "get",
    });
  },
  create(body: WorkspaceModuleForm) {
    return request<ApiResponse<WorkspaceModule>>({
      url: `${API_PATH}/create`,
      method: "post",
      data: body,
    });
  },
  update(id: number, body: Partial<WorkspaceModuleForm>) {
    return request<ApiResponse<WorkspaceModule>>({
      url: `${API_PATH}/update/${id}`,
      method: "put",
      data: body,
    });
  },
  delete(ids: number[]) {
    return request<ApiResponse>({
      url: `${API_PATH}/delete`,
      method: "delete",
      data: ids,
    });
  },
};

export default WorkspaceModuleAPI;
