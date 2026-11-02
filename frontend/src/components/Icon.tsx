import type { ComponentType } from "react";
import {
  Home, Search, BookOpen, Bookmark, Download, Globe, Settings,
  Bell, AlertTriangle, MoreHorizontal, X, LayoutGrid, List,
  BarChart3, Tag, Star, History, FolderUp, Trash2, HardDrive,
  ArrowLeft, ChevronLeft, ChevronRight, Maximize2, Minimize2, SlidersHorizontal, ListOrdered, Pin,
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
  stats: BarChart3,
  tag: Tag,
  star: Star,
  history: History,
  folderUp: FolderUp,
  trash: Trash2,
  storage: HardDrive,
  back: ArrowLeft,
  chevronStart: ChevronLeft,
  chevronEnd: ChevronRight,
  fullscreen: Maximize2,
  fullscreenExit: Minimize2,
  sliders: SlidersHorizontal,
  contents: ListOrdered,
  pin: Pin,
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  const LucideIcon = ICONS[name] ?? MoreHorizontal;
  return <LucideIcon size={size} strokeWidth={1.6} aria-hidden="true" />;
}
