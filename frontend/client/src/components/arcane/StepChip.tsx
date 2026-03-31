// ARCANE StepChip — compact step indicator under agent messages
// Click opens step details in right panel

import { cn } from "@/lib/utils";
import type { Step } from "@/lib/mockData";
import {
  Terminal, Globe, Search, CheckCircle2, XCircle,
  AlertTriangle, Clock, Loader2, SkipForward, Star,
  FileText, Edit3, Eye, MousePointer, Type, ScrollText,
  Image, Palette, MessageSquare, Zap
} from "lucide-react";

// Expanded tool icons for better visual identification
const TOOL_ICONS: Record<string, React.ReactNode> = {
  SSH:              <Terminal size={10} />,
  Terminal:         <Terminal size={10} />,
  Browser:          <Globe size={10} />,
  Search:           <Search size={10} />,
  shell_exec:       <Terminal size={10} />,
  file_write:       <FileText size={10} />,
  file_read:        <Eye size={10} />,
  file_edit:        <Edit3 size={10} />,
  browser_navigate: <Globe size={10} />,
  browser_click:    <MousePointer size={10} />,
  browser_input:    <Type size={10} />,
  browser_scroll:   <ScrollText size={10} />,
  ssh_exec:         <Terminal size={10} />,
  search_web:       <Search size={10} />,
  message:          <MessageSquare size={10} />,
  image_generate:   <Image size={10} />,
  design_judge:     <Palette size={10} />,
};

// Friendly Russian labels for tools — fallback when title is empty
const TOOL_LABELS: Record<string, string> = {
  shell_exec:       "Выполнение команды",
  file_write:       "Запись файла",
  file_read:        "Чтение файла",
  file_edit:        "Редактирование файла",
  browser_navigate: "Открытие страницы",
  browser_click:    "Клик в браузере",
  browser_input:    "Ввод в браузере",
  browser_scroll:   "Прокрутка страницы",
  ssh_exec:         "SSH команда",
  search_web:       "Поиск в интернете",
  message:          "Сообщение",
  image_generate:   "Генерация изображения",
  design_judge:     "Оценка дизайна",
  grep:             "Поиск в файлах",
  file_search:      "Поиск файлов",
};

const STATUS_STYLES: Record<string, { bg: string; text: string; border: string; icon: React.ReactNode }> = {
  success: { bg: "bg-green-50",  text: "text-green-700",  border: "border-green-200", icon: <CheckCircle2 size={10} /> },
  failed:  { bg: "bg-red-50",    text: "text-red-700",    border: "border-red-200",   icon: <XCircle size={10} /> },
  warning: { bg: "bg-amber-50",  text: "text-amber-700",  border: "border-amber-200", icon: <AlertTriangle size={10} /> },
  running: { bg: "bg-blue-50",   text: "text-blue-700",   border: "border-blue-200",  icon: <Loader2 size={10} className="animate-spin" /> },
  queued:  { bg: "bg-gray-50",   text: "text-gray-600",   border: "border-gray-200",  icon: <Clock size={10} /> },
  skipped: { bg: "bg-gray-50",   text: "text-gray-400",   border: "border-gray-200",  icon: <SkipForward size={10} /> },
  partial: { bg: "bg-amber-50",  text: "text-amber-700",  border: "border-amber-200", icon: <AlertTriangle size={10} /> },
};

interface StepChipProps {
  step: Step;
  active?: boolean;
  onClick: (step: Step) => void;
}

export function StepChip({ step, active, onClick }: StepChipProps) {
  const style = STATUS_STYLES[step.status] ?? STATUS_STYLES.queued;
  const toolIcon = TOOL_ICONS[step.tool];
  // Robust title: use step.title, fallback to TOOL_LABELS, then tool name, then "Шаг"
  const displayTitle = step.title || TOOL_LABELS[step.tool] || step.tool || "Шаг";

  return (
    <button
      onClick={() => onClick(step)}
      className={cn(
        "chip-appear inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium border transition-all",
        style.bg, style.text, style.border,
        active && "ring-1 ring-indigo-400 ring-offset-1",
        "hover:brightness-95 cursor-pointer"
      )}
    >
      {style.icon}
      {toolIcon && <span className="opacity-60">{toolIcon}</span>}
      <span className="max-w-[180px] truncate">{displayTitle}</span>
      {step.goldenPath && (
        <Star size={9} className="text-amber-500 shrink-0" fill="currentColor" />
      )}
      {step.duration && step.duration !== "..." && (
        <span className="opacity-50 font-mono text-[10px]">{step.duration}</span>
      )}
    </button>
  );
}
