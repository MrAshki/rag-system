import {
  Archive,
  AudioLines,
  BadgeCheck,
  BookOpen,
  Blocks,
  ChevronDown,
  Cpu,
  Edit3,
  FileOutput,
  FilePenLine,
  FileText,
  GraduationCap,
  Headphones,
  LayoutTemplate,
  List,
  Mic,
  MoreHorizontal,
  Plus,
  Search,
  Send,
  Share2,
  Sparkles,
  SplitSquareHorizontal,
  Sun,
  Trash2,
  Type,
  User,
  Video,
  Waves,
  X,
  MessageSquare,
} from "lucide-react";

type AppIconName =
  | "chat"
  | "file"
  | "plus"
  | "send"
  | "mic"
  | "wave"
  | "settings"
  | "x"
  | "more"
  | "edit"
  | "trash"
  | "share"
  | "theme"
  | "user"
  | "chevron"
  | "library"
  | "output"
  | "template"
  | "summary"
  | "key"
  | "compare"
  | "search"
  | "article"
  | "exam"
  | "flashcard"
  | "simple"
  | "legal"
  | "check"
  | "contract"
  | "audio"
  | "video"
  | "stt"
  | "tts"
  | "provider";

export function AppIcon({ name }: { name: AppIconName }) {
  const props = { "aria-hidden": true, focusable: false } as const;
  if (name === "chat") return <MessageSquare {...props} />;
  if (name === "file") return <FileText {...props} />;
  if (name === "plus") return <Plus {...props} />;
  if (name === "send") return <Send {...props} />;
  if (name === "mic") return <Mic {...props} />;
  if (name === "wave") return <Waves {...props} />;
  if (name === "settings") return <Cpu {...props} />;
  if (name === "x") return <X {...props} />;
  if (name === "more") return <MoreHorizontal {...props} />;
  if (name === "edit") return <Edit3 {...props} />;
  if (name === "trash") return <Trash2 {...props} />;
  if (name === "share") return <Share2 {...props} />;
  if (name === "theme") return <Sun {...props} />;
  if (name === "user") return <User {...props} />;
  if (name === "chevron") return <ChevronDown {...props} />;
  if (name === "library") return <Archive {...props} />;
  if (name === "output") return <FileOutput {...props} />;
  if (name === "template") return <LayoutTemplate {...props} />;
  if (name === "summary") return <List {...props} />;
  if (name === "key") return <FileText {...props} />;
  if (name === "compare") return <SplitSquareHorizontal {...props} />;
  if (name === "search") return <Search {...props} />;
  if (name === "article") return <BookOpen {...props} />;
  if (name === "exam") return <GraduationCap {...props} />;
  if (name === "flashcard") return <BadgeCheck {...props} />;
  if (name === "simple") return <List {...props} />;
  if (name === "legal") return <FilePenLine {...props} />;
  if (name === "check") return <BadgeCheck {...props} />;
  if (name === "contract") return <FileText {...props} />;
  if (name === "audio") return <Headphones {...props} />;
  if (name === "video") return <Video {...props} />;
  if (name === "stt") return <AudioLines {...props} />;
  if (name === "tts") return <Type {...props} />;
  if (name === "provider") return <Blocks {...props} />;
  return <Sparkles {...props} />;
}
