import { request } from "@utils";
export interface SpeechConfig {
  catalog_model_id: number | null;
  status: "active" | "inactive";
  max_duration_seconds: number;
  daily_limit_seconds: number;
  revision: number;
}
export interface SpeechModel {
  id: number;
  name: string;
  provider_name: string;
  provider_model_id: string;
  status: "active" | "inactive";
}
export default {
  config: () =>
    request<ApiResponse<SpeechConfig>>({ url: "/operations/models/speech/config", method: "get" }),
  models: () =>
    request<ApiResponse<SpeechModel[]>>({ url: "/operations/models/speech/models", method: "get" }),
  save: (data: SpeechConfig) =>
    request<ApiResponse<SpeechConfig>>({
      url: "/operations/models/speech/config",
      method: "put",
      data,
    }),
};
