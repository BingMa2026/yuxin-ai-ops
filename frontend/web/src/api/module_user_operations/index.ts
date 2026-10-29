import { request, type ExtendedRequestConfig } from "@utils";

export type TicketStatus = "pending" | "processing" | "waiting_user" | "resolved" | "closed";
export interface SupportMessage extends BaseType {
  sender_type: "client" | "staff";
  sender_id: number;
  content: string;
  attachments: { name: string; url: string; size?: number }[];
  internal: boolean;
}
export interface SupportTicket extends BaseType {
  user_id: number;
  username?: string;
  display_name?: string;
  ticket_no: string;
  kind: "complaint" | "feedback";
  category: string;
  subject: string;
  content: string;
  attachments: { name: string; url: string; size?: number }[];
  priority: "low" | "normal" | "high" | "urgent";
  status: TicketStatus;
  assignee_id?: number;
  sla_due_at: string;
  resolved_at?: string;
  adopted: boolean;
  value_grade?: "S" | "A" | "B" | "C" | null;
  messages: SupportMessage[];
}

export interface MessageTemplate extends BaseType {
  name: string;
  title: string;
  content: string;
  content_type: "plain_text" | "rich_text";
  status: "active" | "inactive";
}

export interface MessageCampaign extends BaseType {
  template_id?: number;
  name: string;
  title: string;
  content: string;
  content_type: "plain_text" | "rich_text";
  audience_type: "all" | "new" | "level" | "segment" | "users";
  audience_value: Record<string, unknown>;
  scheduled_at?: string;
  timezone: string;
  sent_at?: string;
  status: "draft" | "scheduled" | "sending" | "sent" | "cancelled" | "failed";
  target_count: number;
  delivered_count: number;
  read_count: number;
}

export interface MessageDelivery extends BaseType {
  user_id: number;
  username: string;
  display_name?: string;
  campaign_id?: number;
  message_type: string;
  title: string;
  content: string;
  content_type: string;
  resource_type?: string;
  resource_id?: string;
  delivered_at: string;
  read_at?: string;
  status: string;
}

const UserOperationsAPI = {
  deliveries: (
    params: PageQuery & { keyword?: string; message_type?: string; read_status?: string }
  ) =>
    request<ApiResponse<PageResult<MessageDelivery>>>({
      url: "/operations/user-operations/message-deliveries",
      method: "get",
      params,
    }),
  tickets: (
    params: PageQuery & {
      keyword?: string;
      kind?: string;
      category?: string;
      status?: string;
      priority?: string;
    }
  ) =>
    request<ApiResponse<PageResult<SupportTicket>>>({
      url: "/operations/user-operations/tickets",
      method: "get",
      params,
    }),
  ticket: (id: number) =>
    request<ApiResponse<SupportTicket>>({
      url: `/operations/user-operations/tickets/${id}`,
      method: "get",
    }),
  updateTicket: (
    id: number,
    data: Partial<
      Pick<SupportTicket, "priority" | "status" | "assignee_id" | "adopted" | "value_grade">
    >
  ) =>
    request<ApiResponse<SupportTicket>>({
      url: `/operations/user-operations/tickets/${id}`,
      method: "patch",
      data,
    }),
  replyTicket: (
    id: number,
    data: { content: string; internal: boolean; attachments?: SupportMessage["attachments"] }
  ) =>
    request<ApiResponse<SupportMessage>>({
      url: `/operations/user-operations/tickets/${id}/messages`,
      method: "post",
      data,
    }),
  templates: () =>
    request<ApiResponse<MessageTemplate[]>>({
      url: "/operations/user-operations/message-templates",
      method: "get",
    }),
  createTemplate: (data: Omit<MessageTemplate, keyof BaseType>) =>
    request<ApiResponse<MessageTemplate>>({
      url: "/operations/user-operations/message-templates",
      method: "post",
      data,
    }),
  updateTemplate: (id: number, data: Partial<Omit<MessageTemplate, keyof BaseType>>) =>
    request<ApiResponse<MessageTemplate>>({
      url: `/operations/user-operations/message-templates/${id}`,
      method: "patch",
      data,
    }),
  campaigns: () =>
    request<ApiResponse<MessageCampaign[]>>({
      url: "/operations/user-operations/campaigns",
      method: "get",
    }),
  createCampaign: (
    data: Omit<
      MessageCampaign,
      keyof BaseType | "sent_at" | "status" | "target_count" | "delivered_count" | "read_count"
    > & { send_now: boolean }
  ) =>
    request<ApiResponse<MessageCampaign>>({
      url: "/operations/user-operations/campaigns",
      method: "post",
      data,
    }),
  updateCampaign: (id: number, data: Partial<MessageCampaign>) =>
    request<ApiResponse<MessageCampaign>>({
      url: `/operations/user-operations/campaigns/${id}`,
      method: "patch",
      data,
    }),
  cancelCampaign: (id: number) =>
    request<ApiResponse<MessageCampaign>>({
      url: `/operations/user-operations/campaigns/${id}/cancel`,
      method: "post",
    }),
  previewAudience: (data: {
    audience_type: MessageCampaign["audience_type"];
    audience_value: Record<string, unknown>;
  }) =>
    request<
      ApiResponse<{
        target_count: number;
        sample_users: { id: number; name: string; level_code: string }[];
      }>
    >({
      url: "/operations/user-operations/campaigns/audience-preview",
      method: "post",
      data,
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
};

export default UserOperationsAPI;
