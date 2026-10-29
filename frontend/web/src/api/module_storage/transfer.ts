import { request } from "@utils";

const API_PATH = "/storage/transfer";

const TransferAPI = {
  pageTask(query: TransferTaskQuery) {
    return request<ApiResponse<PageResult<TransferTask>>>({
      url: `${API_PATH}/task/page`,
      method: "get",
      params: query,
    });
  },

  detailTask(id: number) {
    return request<ApiResponse<TransferTask>>({
      url: `${API_PATH}/task/${id}`,
      method: "get",
    });
  },

  createRemoteTask(body: TransferTaskCreate) {
    return request<ApiResponse<{ id: number }>>({
      url: `${API_PATH}/task`,
      method: "post",
      data: body,
    });
  },

  createLocalTask(formData: FormData) {
    return request<ApiResponse<{ id: number }>>({
      url: `${API_PATH}/task/upload`,
      method: "post",
      data: formData,
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  cancelTask(id: number) {
    return request<ApiResponse<null>>({
      url: `${API_PATH}/task/${id}/cancel`,
      method: "post",
    });
  },

  deleteTask(ids: number[]) {
    return request<ApiResponse<null>>({
      url: `${API_PATH}/task`,
      method: "delete",
      data: ids,
    });
  },
};

export default TransferAPI;

export type TransferStatus = "pending" | "running" | "success" | "failed" | "canceled";
export type TransferTaskType = "parallel" | "chain";
export type TransferSourceType = "local" | "remote";

export interface TransferTarget {
  target_id: number;
  target_path: string;
}

export interface TransferTaskCreate {
  name: string;
  task_type: TransferTaskType;
  source_type: "remote";
  source_id: number;
  source_path: string;
  targets: TransferTarget[];
}

export interface TransferStep extends BaseType {
  task_id: number;
  step_order: number;
  source_id?: number | null;
  source_path?: string | null;
  target_id: number;
  target_path: string;
  status: TransferStatus;
  progress: number;
  speed: number;
  total_size: number;
  transferred_size: number;
  error_msg?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface TransferTask extends BaseType {
  name: string;
  task_type: TransferTaskType;
  source_type: TransferSourceType;
  source_id?: number | null;
  source_path?: string | null;
  source_name?: string | null;
  source_size?: number | null;
  status: TransferStatus;
  total_size: number;
  transferred_size: number;
  progress: number;
  speed: number;
  error_msg?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  steps?: TransferStep[];
}

export interface TransferTaskQuery extends PageQuery {
  name?: string;
  task_type?: TransferTaskType;
  status?: TransferStatus;
}
