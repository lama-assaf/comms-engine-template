// The pages, their words and their icons, in menu order. Each page's colour is
// its own (genome.ts pageColor), so a page looks the same in the rail, the tab
// bar, the More sheet and its own head.
import {
  BarChart3, BookOpen, Ear, FileText, Hash, Heart, House, MessageSquare, Search, Settings, ShieldCheck, SlidersHorizontal, Sparkles, Users, type LucideIcon,
} from "lucide-react";

export interface PageMeta { key: string; label: string; icon: LucideIcon; group?: string }

export const PAGES: PageMeta[] = [
  { key: "story", label: "Story", icon: BookOpen },
  { key: "today", label: "Today", icon: House },
  { key: "posts", label: "Posts", icon: FileText, group: "Content" },
  { key: "themes", label: "Themes", icon: Hash },
  { key: "heard", label: "What we heard", icon: Ear },
  { key: "replies", label: "Replies", icon: MessageSquare },
  { key: "engagement", label: "Engagement", icon: Heart },
  { key: "accounts", label: "Accounts", icon: Users, group: "People" },
  { key: "suggestions", label: "Suggestions", icon: Sparkles },
  { key: "claims", label: "Claim ideas", icon: Search, group: "Learning" },
  { key: "results", label: "Results", icon: BarChart3 },
  { key: "autonomy", label: "Autonomy", icon: ShieldCheck, group: "Control" },
  { key: "setup", label: "Setup", icon: SlidersHorizontal },
  { key: "system", label: "System", icon: Settings },
];

export const TABS = ["story", "today", "posts", "themes"];

export const meta = (key: string) => PAGES.find((p) => p.key === key) || PAGES[1];
