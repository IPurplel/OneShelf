import type { ComponentType } from "react";
import {
  Home, Search, BookOpen, Bookmark, Download, Globe, Settings,
  Bell, AlertTriangle, MoreHorizontal, X, LayoutGrid, List,
} from "lucide-react";

const ICONS: Record<string, ComponentType<{ size?: number; strokeWidth?: number }>> = {
  home: Home,
  search: Search,
  shelf: BookOpen,
  following: Bookmark,
  downloads: Download,
  sources: Globe,
  settings: Settings,
  bell: Bell,
  attention: AlertTriangle,
  more: MoreHorizontal,
  close: X,
  grid: LayoutGrid,
  list: List,
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  const LucideIcon = ICONS[name] ?? MoreHorizontal;
  return <LucideIcon size={size} strokeWidth={1.6} aria-hidden="true" />;
}
