import type { StringKey } from "./strings";

type Translate = (key: StringKey) => string;
const CAPABILITIES = new Set(["search", "work", "catalog", "reader", "downloads", "latest", "health"]);
const CHANNELS = new Set(["bundled", "registry", "upload"]);
const TRUST = new Set(["official", "verified_community", "community", "local"]);

const readable = (value: string) => value.replaceAll("_", " ");

export function capabilityLabel(value: string, t: Translate): string {
  return CAPABILITIES.has(value) ? t(`sources.capability.${value}` as StringKey) : readable(value);
}
export function channelLabel(value: string, t: Translate): string {
  return CHANNELS.has(value) ? t(`sources.channel.${value}` as StringKey) : readable(value);
}
export function trustLabel(value: string, t: Translate): string {
  return TRUST.has(value) ? t(`sources.trust.${value}` as StringKey) : readable(value);
}
