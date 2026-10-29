import type { CatalogModel, ProviderAccount, ProviderTemplate } from "@/api/module_model_gateway";

const NON_CHAT_MARKERS = [
  "-asr",
  "-tts",
  "-audio",
  "-embedding",
  "-rerank",
  "-image",
  "image-edit",
  "speech-",
  "livetranslate",
  "realtime",
];

function providerPriority(account?: ProviderAccount) {
  if (account?.status === "active") return 0;
  if (account?.connection_status === "healthy") return 1;
  if (account) return 2;
  return 3;
}

export function sortProviderTemplates(
  templates: ProviderTemplate[],
  accountFor: (template: ProviderTemplate) => ProviderAccount | undefined
) {
  return [...templates].sort((left, right) => {
    const priority = providerPriority(accountFor(left)) - providerPriority(accountFor(right));
    if (priority) return priority;
    return (left.order || 999) - (right.order || 999) || left.name.localeCompare(right.name);
  });
}

export function isChatGatewayCompatible(modelId: string) {
  const normalized = modelId.trim().toLowerCase();
  return (
    !normalized.startsWith("wan") &&
    !normalized.startsWith("z-image") &&
    !NON_CHAT_MARKERS.some((marker) => normalized.includes(marker))
  );
}

export function isSpeechInputModel(modelId: string) {
  return /asr|whisper|transcrib|paraformer|sensevoice/i.test(modelId);
}

function releaseDate(modelId: string) {
  const match = modelId.match(/(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})/);
  return match ? Number(`${match[1]}${match[2]}${match[3]}`) : 0;
}

function semanticVersion(modelId: string) {
  const match = modelId.match(/(?:qwen|gpt|claude|gemini|glm|deepseek)[-_]?(\d+(?:\.\d+)?)/i);
  const versionText = match?.[1];
  if (!match || !versionText) return 0;
  if (modelId[(match.index ?? 0) + match[0].length]?.toLowerCase() === "b") return 0;
  const [major, minor = "0"] = versionText.split(".");
  return Number(major) * 100 + Number(minor);
}

function modelFamily(modelId?: string) {
  return (
    modelId
      ?.trim()
      .toLowerCase()
      .match(/^[a-z]+/)?.[0] || ""
  );
}

function timestamp(value?: string) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function sortCatalogModels(models: CatalogModel[], recommendedModel?: string) {
  const recommended = recommendedModel?.trim().toLowerCase();
  const preferredFamily = modelFamily(recommended);
  return [...models].sort((left, right) => {
    const active = Number(right.status === "active") - Number(left.status === "active");
    if (active) return active;

    const leftId = left.provider_model_id.toLowerCase();
    const rightId = right.provider_model_id.toLowerCase();
    const recommendedPriority = Number(rightId === recommended) - Number(leftId === recommended);
    if (recommendedPriority) return recommendedPriority;

    const preferredFamilyPriority =
      Number(rightId.startsWith(preferredFamily)) - Number(leftId.startsWith(preferredFamily));
    if (preferredFamily && preferredFamilyPriority) return preferredFamilyPriority;

    const compatible =
      Number(isChatGatewayCompatible(rightId)) - Number(isChatGatewayCompatible(leftId));
    if (compatible) return compatible;

    const version = semanticVersion(rightId) - semanticVersion(leftId);
    if (version) return version;

    const date = releaseDate(rightId) - releaseDate(leftId);
    if (date) return date;

    const updated =
      timestamp(right.updated_time || right.created_time) -
      timestamp(left.updated_time || left.created_time);
    if (updated) return updated;
    return left.display_name.localeCompare(right.display_name);
  });
}
