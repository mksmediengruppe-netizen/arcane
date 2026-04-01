// RightPanel — Warm Intelligence design
// Tabs: Live, Browser, Steps, Logs, Files, Verification, Result
// Features: browser preview, file preview with syntax highlighting, task progress

import { useState, useEffect, useRef, useMemo } from "react";
import { cn } from "@/lib/utils";
import { type Step, type LogEntry, type Artifact as MockArtifact } from "@/lib/mockData";
import {
  Activity, ListChecks, ScrollText, FolderOpen, ShieldCheck, Trophy,
  Terminal, Globe, Search, ChevronDown, ChevronRight, Star,
  FileText, FileCode, Image as ImageIcon, Download, Eye, CheckCircle2, XCircle,
  AlertTriangle, Loader2, Clock, X, Circle, Monitor, Copy, Check,
  ArrowLeft, ArrowRight, RefreshCw, Lock, Code2, BarChart2, Layers,
  ExternalLink, Brain, Smartphone, Tablet, Maximize2, Minimize2
} from "lucide-react";
import { SessionInsightsTab } from "@/components/arcane/SessionInsights";
import { AgentBrowser, type BrowserOfflineReason } from "@/components/arcane/AgentBrowser";
import { ArtifactViewer, ArtifactList, DEMO_ARTIFACTS, type Artifact } from "@/components/arcane/ArtifactViewer";
import type { ViewerArtifact } from "@/lib/mockData";
import { motion, AnimatePresence } from "framer-motion";

const TABS = [
  { id: "live",      label: "Live",       icon: <Activity size={13} /> },
  { id: "preview",   label: "Превью",     icon: <Eye size={13} /> },
  { id: "browser",   label: "Браузер",    icon: <Monitor size={13} /> },
  { id: "thinking",  label: "Мышление",   icon: <Brain size={13} /> },
  { id: "artifacts", label: "Артефакты",  icon: <Layers size={13} /> },
  { id: "steps",     label: "Шаги",       icon: <ListChecks size={13} /> },
  { id: "logs",      label: "Логи",       icon: <ScrollText size={13} /> },
];

interface RightPanelProps {
  activeStep?: string;
  onStepSelect: (id: string) => void;
  defaultTab?: string;
  steps?: Step[];
  plan?: string[];
  completedSteps?: number;
  activeStepTitle?: string;
  isRunning?: boolean;
  currentTool?: string | null;
  pendingArtifact?: ViewerArtifact | null;
  onArtifactConsumed?: () => void;
  /** Real-time log entries from SSE events */
  logs?: LogEntry[];
  /** Chat status from backend (e.g. 'working', 'executing', 'thinking') */
  chatStatus?: string;
  /** Thinking content from agent reasoning */
  thinkingContent?: string;
  /** Messages for extracting preview URLs */
  messages?: import("@/lib/mockData").Message[];
}

export function RightPanel({ activeStep, onStepSelect, defaultTab = "live", steps, plan, completedSteps, activeStepTitle, isRunning, currentTool, pendingArtifact, onArtifactConsumed, logs, chatStatus, thinkingContent, messages }: RightPanelProps) {
  const [activeTab, setActiveTab] = useState(defaultTab);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [browserOfflineReason, setBrowserOfflineReason] = useState<BrowserOfflineReason>("none");
  const [isBrowserTakeover, setIsBrowserTakeover] = useState(false);
  const [novncReady, setNovncReady] = useState(false);

  // When a pending artifact arrives from a chat click, open it in the viewer
  useEffect(() => {
    if (pendingArtifact) {
      // Map ViewerArtifact (from mockData) to Artifact (from ArtifactViewer)
      const mapped: Artifact = {
        id: pendingArtifact.id,
        title: pendingArtifact.title,
        type: pendingArtifact.type,
        language: pendingArtifact.language,
        content: pendingArtifact.content,
        originalContent: pendingArtifact.originalContent,
        createdAt: pendingArtifact.createdAt,
        size: pendingArtifact.size,
      };
      setSelectedArtifact(mapped);
      setActiveTab("artifacts");
      onArtifactConsumed?.();
    }
  }, [pendingArtifact, onArtifactConsumed]);

  useEffect(() => {
    setActiveTab(defaultTab);
  }, [defaultTab]);

  return (
    <aside className="flex flex-col h-full bg-white dark:bg-[#0f1117] border-l border-[#E8E6E1] dark:border-[#2a2d3a] w-full">
      {/* Tab bar */}
      <div className="flex items-center border-b border-[#E8E6E1] dark:border-[#2a2d3a] px-0.5 shrink-0 overflow-x-auto" style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
        <style>{`.right-panel-tabs::-webkit-scrollbar { display: none; }`}</style>
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1 px-1.5 py-2.5 text-[11px] font-medium border-b-2 transition-colors whitespace-nowrap shrink-0",
              activeTab === tab.id
                ? "border-indigo-600 text-indigo-700 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            )}
            title={tab.label}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="h-full"
          >
            {activeTab === "live"      && <LiveTab plan={plan} completedSteps={completedSteps} activeStepTitle={activeStepTitle} totalSteps={steps?.length} isRunning={isRunning} currentTool={currentTool} steps={steps} chatStatus={chatStatus} />}
            {activeTab === "preview"   && <PreviewTab messages={messages} isRunning={isRunning} />}
            {activeTab === "browser"   && (
              <div className="h-full flex flex-col">
                {/* Takeover banner */}
                {isBrowserTakeover ? (
                  <div className="shrink-0 border-b border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 px-3 py-2 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
                    <Monitor size={12} className="text-amber-600 shrink-0" />
                    <span className="text-[11px] font-semibold text-amber-800 dark:text-amber-300 flex-1">Режим управления браузером</span>
                    <button
                      onClick={() => { setIsBrowserTakeover(false); setNovncReady(false); }}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-amber-200 dark:bg-amber-800 text-amber-800 dark:text-amber-200 text-[10px] font-medium hover:bg-amber-300 transition-colors"
                    >
                      <X size={9} />
                      Вернуть агенту
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Takeover button bar */}
                    <div className="shrink-0 border-b border-gray-100 dark:border-[#2a2d3a] bg-gray-50 dark:bg-[#1a1d2e] px-2 py-1 flex items-center gap-1 overflow-x-auto">
                      <button
                        onClick={() => { setIsBrowserTakeover(true); setNovncReady(false); }}
                        className="flex items-center gap-1 px-2.5 py-1 rounded bg-indigo-600 text-white text-[10px] font-medium hover:bg-indigo-700 transition-colors shrink-0"
                      >
                        <Monitor size={10} />
                        Управлять браузером
                      </button>
                      {browserOfflineReason === "none" && (
                        <>
                          <span className="text-[10px] text-gray-300 dark:text-gray-600 mx-1">|</span>
                          <span className="text-[10px] text-gray-400 shrink-0">Demo:</span>
                          <button onClick={() => setBrowserOfflineReason("sandbox_unavailable")} className="px-2 py-0.5 rounded text-[10px] bg-red-50 text-red-600 hover:bg-red-100 transition-colors whitespace-nowrap">Sandbox offline</button>
                          <button onClick={() => setBrowserOfflineReason("permission_denied")} className="px-2 py-0.5 rounded text-[10px] bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors whitespace-nowrap">Permission denied</button>
                          <button onClick={() => setBrowserOfflineReason("reconnecting")} className="px-2 py-0.5 rounded text-[10px] bg-amber-50 text-amber-600 hover:bg-amber-100 transition-colors whitespace-nowrap">Reconnecting</button>
                        </>
                      )}
                      {browserOfflineReason !== "none" && (
                        <button onClick={() => setBrowserOfflineReason("none")} className="ml-auto px-2 py-0.5 rounded text-[10px] bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-300 transition-colors">Сбросить</button>
                      )}
                    </div>
                  </>
                )}
                {/* Content: noVNC iframe or AgentBrowser */}
                <div className="flex-1 overflow-hidden relative">
                  {isBrowserTakeover ? (
                    <>
                      {!novncReady && (
                        <div className="absolute inset-0 flex items-center justify-center bg-gray-900 z-10">
                          <div className="flex flex-col items-center gap-3 text-center">
                            <Loader2 size={24} className="text-indigo-400 animate-spin" />
                            <span className="text-sm text-gray-300">Подключение к браузеру...</span>
                            <span className="text-xs text-gray-500">noVNC — интерактивное управление</span>
                          </div>
                        </div>
                      )}
                      <iframe
                        src="/novnc/vnc.html?autoconnect=1&reconnect=1&resize=scale&show_dot=1&path=novnc/websockify"
                        className="w-full h-full border-0"
                        allow="clipboard-read; clipboard-write"
                        onLoad={() => setNovncReady(true)}
                        title="Browser Takeover — noVNC"
                      />
                    </>
                  ) : (
                    <AgentBrowser isRunning={isRunning} offlineReason={browserOfflineReason} onRetry={() => setBrowserOfflineReason("none")} />
                  )}
                </div>
              </div>
            )}
            {activeTab === "artifacts" && (
              selectedArtifact
                ? <ArtifactViewer artifact={selectedArtifact} onClose={() => setSelectedArtifact(null)} className="h-full rounded-none border-0" />
                : <ArtifactList artifacts={[]} onSelect={setSelectedArtifact} />
            )}
            {activeTab === "thinking"  && <ThinkingTab thinkingContent={thinkingContent} isRunning={isRunning} />}
            {activeTab === "steps"     && <StepsTab activeStep={activeStep} onStepSelect={onStepSelect} steps={steps} />}
            {activeTab === "logs"      && <LogsTab steps={steps} logs={logs} />}
            {false && activeTab === "files"     && <FilesTab steps={steps} />}
            {false && activeTab === "insights"  && <SessionInsightsTab />}
            {false && activeTab === "verify"    && <VerifyTab />}
            {false && activeTab === "result"    && <ResultTab />}
          </motion.div>
        </AnimatePresence>
      </div>
    </aside>
  );
}


// ─── Preview Tab ──────────────────────────────────────────────────────────────

type ViewportSize = "desktop" | "tablet" | "mobile";

const VIEWPORT_SIZES: Record<ViewportSize, { width: string; label: string; icon: React.ReactNode }> = {
  desktop: { width: "100%", label: "Десктоп", icon: <Monitor size={14} /> },
  tablet:  { width: "768px", label: "Планшет", icon: <Tablet size={14} /> },
  mobile:  { width: "375px", label: "Мобильный", icon: <Smartphone size={14} /> },
};

function PreviewTab({ messages, isRunning }: { messages?: import("@/lib/mockData").Message[]; isRunning?: boolean }) {
  const [viewport, setViewport] = useState<ViewportSize>("desktop");
  const [customUrl, setCustomUrl] = useState("");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Extract preview URL from messages — look for arcaneai.ru/demo/ URLs
  const previewUrl = useMemo(() => {
    if (customUrl) return customUrl;
    if (!messages || messages.length === 0) return "";
    
    // Search messages in reverse for the latest deploy URL
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      
      // Check attachments for preview_url
      if (msg.attachments) {
        for (const att of msg.attachments) {
          if (att.preview_url && att.preview_url.includes("/demo/")) return att.preview_url;
          if (att.download_url && att.download_url.includes("/demo/")) return att.download_url;
        }
      }
      
      // Check message content for arcaneai.ru/demo/ URLs
      if (msg.content) {
        const urlMatch = msg.content.match(/https?:\/\/arcaneai\.ru\/demo\/[^\s"'<>)]+/);
        if (urlMatch) return urlMatch[0];
        // Also check for any URL with /demo/
        const demoMatch = msg.content.match(/https?:\/\/[^\s"'<>)]*\/demo\/[^\s"'<>)]+/);
        if (demoMatch) return demoMatch[0];
      }
    }
    return "";
  }, [messages, customUrl]);

  const handleRefresh = () => {
    if (iframeRef.current) {
      setIsLoading(true);
      iframeRef.current.src = iframeRef.current.src;
    }
  };

  const toggleFullscreen = () => {
    if (!isFullscreen && containerRef.current) {
      containerRef.current.requestFullscreen?.();
      setIsFullscreen(true);
    } else if (isFullscreen) {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  if (!previewUrl) {
    return (
      <div className="flex flex-col h-full">
        {/* URL input bar */}
        <div className="shrink-0 border-b border-gray-100 dark:border-[#2a2d3a] bg-gray-50 dark:bg-[#1a1d2e] px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Globe size={14} className="text-gray-400 shrink-0" />
            <input
              type="text"
              value={customUrl}
              onChange={e => setCustomUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && customUrl && setCustomUrl(customUrl)}
              placeholder="Вставьте URL лендинга для предпросмотра..."
              className="flex-1 bg-white dark:bg-[#0f1117] border border-gray-200 dark:border-[#2a2d3a] rounded-lg px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
            />
          </div>
        </div>
        {/* Empty state */}
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center space-y-3">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/40 dark:to-purple-900/40 flex items-center justify-center mx-auto">
              <Eye size={28} className="text-indigo-400" />
            </div>
            <div className="space-y-1">
              <div className="text-sm font-medium text-gray-500 dark:text-gray-400">Превью недоступно</div>
              <div className="text-xs text-gray-400 dark:text-gray-500 max-w-[240px]">
                {isRunning 
                  ? "Агент ещё работает. Превью появится после деплоя лендинга."
                  : "Вставьте URL выше или отправьте задачу агенту для создания лендинга."
                }
              </div>
            </div>
            {isRunning && (
              <div className="flex items-center justify-center gap-2 text-xs text-indigo-500">
                <Loader2 size={12} className="animate-spin" />
                <span>Ожидание деплоя...</span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col h-full bg-gray-100 dark:bg-[#0a0c14]">
      {/* Toolbar */}
      <div className="shrink-0 border-b border-gray-200 dark:border-[#2a2d3a] bg-white dark:bg-[#0f1117] px-3 py-2 space-y-2">
        {/* URL bar */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={handleRefresh} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" title="Обновить">
              <RefreshCw size={13} className={cn("text-gray-500", isLoading && "animate-spin")} />
            </button>
          </div>
          <div className="flex-1 flex items-center gap-1.5 bg-gray-50 dark:bg-[#1a1d2e] border border-gray-200 dark:border-[#2a2d3a] rounded-lg px-2.5 py-1.5">
            <Lock size={10} className="text-green-500 shrink-0" />
            <span className="text-[11px] text-gray-600 dark:text-gray-400 font-mono truncate flex-1">{previewUrl}</span>
          </div>
          <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" title="Открыть в новой вкладке">
            <ExternalLink size={13} className="text-gray-500" />
          </a>
          <button onClick={toggleFullscreen} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" title={isFullscreen ? "Выйти из полноэкранного" : "Полноэкранный режим"}>
            {isFullscreen ? <Minimize2 size={13} className="text-gray-500" /> : <Maximize2 size={13} className="text-gray-500" />}
          </button>
        </div>
        {/* Viewport controls */}
        <div className="flex items-center gap-1">
          {(Object.entries(VIEWPORT_SIZES) as [ViewportSize, typeof VIEWPORT_SIZES[ViewportSize]][]).map(([key, val]) => (
            <button
              key={key}
              onClick={() => setViewport(key)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all",
                viewport === key
                  ? "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800"
                  : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              )}
            >
              {val.icon}
              {val.label}
            </button>
          ))}
          <div className="ml-auto text-[10px] text-gray-400 font-mono">
            {VIEWPORT_SIZES[viewport].width === "100%" ? "100%" : VIEWPORT_SIZES[viewport].width}
          </div>
        </div>
      </div>
      
      {/* iframe container */}
      <div className="flex-1 overflow-hidden flex items-start justify-center p-2">
        <div 
          className={cn(
            "h-full bg-white dark:bg-white rounded-lg shadow-lg overflow-hidden transition-all duration-300 border border-gray-200 dark:border-gray-700",
            viewport === "desktop" ? "w-full" : ""
          )}
          style={viewport !== "desktop" ? { width: VIEWPORT_SIZES[viewport].width, maxWidth: "100%" } : undefined}
        >
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-gray-900/80 z-10">
              <Loader2 size={24} className="text-indigo-500 animate-spin" />
            </div>
          )}
          <iframe
            ref={iframeRef}
            src={previewUrl}
            className="w-full h-full border-0"
            onLoad={() => setIsLoading(false)}
            title="Landing Page Preview"
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          />
        </div>
      </div>
    </div>
  );
}

// ─── Thinking Tab ─────────────────────────────────────────────────────────────

function ThinkingTab({ thinkingContent, isRunning }: { thinkingContent?: string; isRunning?: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [thinkingContent, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
  };

  if (!thinkingContent) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-6 text-center">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-100 to-indigo-100 dark:from-purple-900/40 dark:to-indigo-900/40 flex items-center justify-center mb-3">
          <Brain size={24} className="text-purple-400 dark:text-purple-500" />
        </div>
        <div className="text-sm font-medium text-gray-400 dark:text-gray-500">Размышления агента</div>
        <div className="text-xs text-gray-300 dark:text-gray-600 mt-1 max-w-[240px]">
          {isRunning 
            ? "Агент думает... Размышления появятся здесь в реальном времени."
            : "Здесь будут отображаться мысли и рассуждения агента во время выполнения задачи."
          }
        </div>
        {isRunning && (
          <div className="flex items-center gap-2 mt-3">
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" style={{ animationDelay: "0.2s" }} />
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" style={{ animationDelay: "0.4s" }} />
          </div>
        )}
      </div>
    );
  }

  // Parse thinking content into blocks
  const blocks = thinkingContent.split("\n").filter(line => line.trim());

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 border-b border-gray-100 dark:border-[#2a2d3a] bg-gray-50 dark:bg-[#1a1d2e] px-3 py-2 flex items-center gap-2">
        <Brain size={14} className="text-purple-500" />
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">Размышления агента</span>
        {isRunning && (
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
            <span className="text-[10px] text-purple-500 font-medium">В процессе</span>
          </div>
        )}
        {!isRunning && (
          <span className="text-[10px] text-gray-400 ml-auto font-mono">{blocks.length} блоков</span>
        )}
      </div>

      {/* Content */}
      <div 
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 space-y-3"
        style={{ scrollbarWidth: "thin" }}
      >
        {blocks.map((block, i) => {
          const isLast = i === blocks.length - 1;
          const isAction = block.startsWith("→") || block.startsWith("->") || block.includes("решил") || block.includes("нужно") || block.includes("буду");
          const isQuestion = block.includes("?");
          const isConclusion = block.startsWith("✓") || block.startsWith("Итого") || block.startsWith("Вывод") || block.startsWith("Результат");
          
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.02, 0.5) }}
              className={cn(
                "text-[12px] leading-relaxed px-3 py-2.5 rounded-xl border-l-2",
                isConclusion
                  ? "bg-green-50 dark:bg-green-950/30 border-green-400 text-green-800 dark:text-green-300"
                  : isAction
                    ? "bg-indigo-50 dark:bg-indigo-950/30 border-indigo-400 text-indigo-800 dark:text-indigo-300"
                    : isQuestion
                      ? "bg-amber-50 dark:bg-amber-950/30 border-amber-400 text-amber-800 dark:text-amber-300"
                      : "bg-gray-50 dark:bg-gray-900/50 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300",
                isLast && isRunning && "ring-1 ring-purple-200 dark:ring-purple-800"
              )}
            >
              {block}
              {isLast && isRunning && (
                <span className="inline-block ml-1 w-1.5 h-4 bg-purple-400 animate-pulse rounded-sm" />
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true);
            if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          }}
          className="absolute bottom-4 right-4 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-purple-600 text-white text-[11px] font-medium shadow-lg hover:bg-purple-700 transition-colors"
        >
          <ChevronDown size={12} />
          Новые мысли
        </button>
      )}
    </div>
  );
}


// ─── Live Tab ────────────────────────────────────────────────────────────────

// ─── Tool name to beautiful Russian description mapping ─────────────────────
const TOOL_DESCRIPTIONS: Record<string, { icon: string; label: string; color: string }> = {
  web_search:       { icon: "🔍", label: "Ищу информацию в интернете",     color: "text-blue-600 dark:text-blue-400" },
  browser_navigate: { icon: "🌐", label: "Открываю веб-страницу",          color: "text-blue-600 dark:text-blue-400" },
  browser_view:     { icon: "👁",  label: "Изучаю содержимое страницы",     color: "text-blue-600 dark:text-blue-400" },
  browser_click:    { icon: "👆", label: "Взаимодействую со страницей",    color: "text-blue-600 dark:text-blue-400" },
  browser_scroll:   { icon: "📜", label: "Прокручиваю страницу",           color: "text-blue-600 dark:text-blue-400" },
  image_generate:   { icon: "🎨", label: "Генерирую изображение",          color: "text-purple-600 dark:text-purple-400" },
  file_write:       { icon: "📝", label: "Создаю файл",                    color: "text-green-600 dark:text-green-400" },
  file_edit:        { icon: "✏️",  label: "Редактирую файл",               color: "text-green-600 dark:text-green-400" },
  file_create:      { icon: "📄", label: "Создаю новый файл",              color: "text-green-600 dark:text-green-400" },
  file_read:        { icon: "📖", label: "Читаю файл",                     color: "text-green-600 dark:text-green-400" },
  shell_exec:       { icon: "💻", label: "Выполняю команду в терминале",   color: "text-amber-600 dark:text-amber-400" },
  get_template:     { icon: "📋", label: "Загружаю шаблон дизайна",        color: "text-indigo-600 dark:text-indigo-400" },
  plan:             { icon: "📐", label: "Составляю план работы",          color: "text-indigo-600 dark:text-indigo-400" },
  update_scratchpad:{ icon: "📒", label: "Сохраняю данные в блокнот",      color: "text-yellow-600 dark:text-yellow-400" },
  message:          { icon: "💬", label: "Отправляю результат",            color: "text-emerald-600 dark:text-emerald-400" },
  deploy_to_vps:    { icon: "🚀", label: "Публикую на сервер",             color: "text-rose-600 dark:text-rose-400" },
  create_archive:   { icon: "📦", label: "Создаю архив",                   color: "text-amber-600 dark:text-amber-400" },
  design_judge:     { icon: "🏆", label: "Оцениваю качество дизайна",      color: "text-purple-600 dark:text-purple-400" },
  ssh_exec:         { icon: "🖥️",  label: "Выполняю команду на сервере",   color: "text-amber-600 dark:text-amber-400" },
};

const PHASE_LABELS: Record<string, { icon: string; label: string }> = {
  planning:   { icon: "📐", label: "Планирование" },
  coding:     { icon: "💻", label: "Разработка" },
  deploying:  { icon: "🚀", label: "Публикация" },
  verifying:  { icon: "✅", label: "Проверка" },
  delivering: { icon: "📬", label: "Доставка результата" },
};

function getToolInfo(toolName: string) {
  return TOOL_DESCRIPTIONS[toolName] || { icon: "⚙️", label: toolName.replace(/_/g, " "), color: "text-gray-600 dark:text-gray-400" };
}

function LiveTab({ plan, completedSteps = 0, activeStepTitle, totalSteps, isRunning, currentTool, steps, chatStatus }: {
  plan?: string[];
  completedSteps?: number;
  activeStepTitle?: string;
  totalSteps?: number;
  isRunning: boolean;
  currentTool?: string;
  steps?: any[];
  chatStatus?: string;
}) {
  const effectiveLog = steps || [];
  const hasPlan = plan && plan.length > 0;
  const isAgentActive = isRunning || chatStatus === "working";

  const getToolInfo = (tool: string) => {
    const map: Record<string, { icon: string; label: string; color: string }> = {
      browser_navigate: { icon: "🌐", label: "Браузер", color: "text-blue-600" },
      browser_click: { icon: "👆", label: "Нажатие", color: "text-blue-600" },
      browser_input: { icon: "⌨️", label: "Ввод текста", color: "text-blue-600" },
      browser_scroll: { icon: "📜", label: "Прокрутка", color: "text-blue-600" },
      browser_view: { icon: "👁️", label: "Просмотр", color: "text-blue-600" },
      browser_find_keyword: { icon: "🔍", label: "Поиск", color: "text-blue-600" },
      browser_save_image: { icon: "📷", label: "Сохранение", color: "text-blue-600" },
      file_write: { icon: "📝", label: "Запись файла", color: "text-emerald-600" },
      file_read: { icon: "📄", label: "Чтение файла", color: "text-emerald-600" },
      file_edit: { icon: "✏️", label: "Редактирование", color: "text-emerald-600" },
      shell_exec: { icon: "💻", label: "Терминал", color: "text-amber-600" },
      search: { icon: "🔎", label: "Поиск", color: "text-purple-600" },
      message: { icon: "💬", label: "Сообщение", color: "text-gray-600" },
    };
    return map[tool] || { icon: "⚡", label: tool || "Инструмент", color: "text-gray-600" };
  };

  if (!isAgentActive && effectiveLog.length === 0 && !hasPlan) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 px-6">
        <div className="w-14 h-14 rounded-2xl bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
          <Monitor size={24} className="text-gray-300 dark:text-gray-600" />
        </div>
        <div className="text-sm font-medium text-gray-400 dark:text-gray-500">Задача не запущена</div>
        <div className="text-xs text-gray-300 dark:text-gray-600 mt-1">Отправьте задачу агенту</div>
      </div>
    );
  }

  const toolInfo = currentTool ? getToolInfo(currentTool) : null;

  return (
    <div className="flex flex-col h-full">
      {/* Header — "ARCANE's Computer" style like Manus */}
      <div className="shrink-0 px-4 py-3 border-b border-gray-100 dark:border-[#2a2d3a]">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-5 h-5 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center">
            <Monitor size={11} className="text-green-600 dark:text-green-400" />
          </div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Компьютер ARCANE</h3>
          {isAgentActive && <Loader2 size={12} className="text-gray-400 animate-spin ml-auto" />}
        </div>
        {isAgentActive && toolInfo && (
          <div className="text-xs text-gray-500 dark:text-gray-400 ml-7">
            ARCANE использует <span className="font-medium text-gray-700 dark:text-gray-300">{toolInfo.label}</span>
          </div>
        )}
        {!isAgentActive && effectiveLog.length > 0 && (
          <div className="flex items-center gap-1.5 ml-7">
            <CheckCircle2 size={12} className="text-green-500" />
            <span className="text-xs text-green-600 dark:text-green-400 font-medium">Задача завершена</span>
          </div>
        )}
      </div>

      {/* Main content — browser-like preview area */}
      <div className="flex-1 overflow-y-auto">
        {/* Browser screenshot placeholder */}
        <div className="p-3">
          <div className="rounded-xl border border-gray-200 dark:border-[#2a2d3a] overflow-hidden bg-gray-50 dark:bg-[#0d0f1a]">
            {/* URL bar */}
            {currentTool && currentTool.startsWith("browser") && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-white dark:bg-[#1a1d2e] border-b border-gray-100 dark:border-[#2a2d3a]">
                <Globe size={10} className="text-gray-400 shrink-0" />
                <span className="text-[10px] text-gray-400 font-mono truncate">Браузер агента</span>
              </div>
            )}
            {/* Preview content area */}
            <div className="aspect-video flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100 dark:from-[#0d0f1a] dark:to-[#1a1d2e]">
              {isAgentActive ? (
                <div className="flex flex-col items-center gap-3">
                  <div className="relative">
                    <div className="w-16 h-16 rounded-2xl bg-white dark:bg-[#1a1d2e] border border-gray-200 dark:border-[#2a2d3a] flex items-center justify-center shadow-sm">
                      <span className="text-2xl">{toolInfo?.icon || "⚡"}</span>
                    </div>
                    <div className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center">
                      <Loader2 size={10} className="text-white animate-spin" />
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-xs font-medium text-gray-600 dark:text-gray-300">{toolInfo?.label || "Работает"}</div>
                    <div className="text-[10px] text-gray-400 mt-0.5">{currentTool}</div>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <CheckCircle2 size={32} className="text-green-400" />
                  <span className="text-xs text-gray-400">Завершено</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Task Progress — plan checklist */}
        {hasPlan && (
          <div className="px-4 pb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Прогресс</span>
              <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400">
                {completedSteps} / {plan!.length}
              </span>
            </div>
            {/* Progress bar */}
            <div className="w-full bg-gray-100 dark:bg-gray-800 rounded-full h-1 mb-3">
              <motion.div
                className="bg-blue-500 h-1 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: plan!.length > 0 ? `${(completedSteps / plan!.length) * 100}%` : "0%" }}
                transition={{ duration: 0.4, ease: "easeOut" }}
              />
            </div>
            <div className="space-y-0.5">
              {plan!.map((item, i) => {
                const done = i < completedSteps;
                const running = i === completedSteps && isAgentActive;
                return (
                  <div key={i} className={cn(
                    "flex items-start gap-2 text-xs px-2 py-1.5 rounded-lg",
                    running ? "bg-blue-50 dark:bg-blue-950/20" : ""
                  )}>
                    {done ? (
                      <CheckCircle2 size={13} className="text-green-500 shrink-0 mt-0.5" />
                    ) : running ? (
                      <Loader2 size={13} className="text-blue-500 animate-spin shrink-0 mt-0.5" />
                    ) : (
                      <Circle size={13} className="text-gray-300 dark:text-gray-600 shrink-0 mt-0.5" />
                    )}
                    <span className={cn(
                      done ? "text-gray-400 line-through" : running ? "text-gray-800 dark:text-gray-200 font-medium" : "text-gray-400"
                    )}>
                      {item}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recent actions log */}
        {effectiveLog.length > 0 && (
          <div className="px-4 pb-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Лог действий</span>
            </div>
            <div className="space-y-0.5">
              {effectiveLog.slice(-12).map((step: any, i: number) => {
                const info = getToolInfo(step.tool || "");
                const isDone = step.status === "success" || step.status === "completed";
                const isActive = step.status === "running";
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.15, delay: i * 0.02 }}
                    className={cn(
                      "flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs",
                      isActive ? "bg-blue-50 dark:bg-blue-950/20" : ""
                    )}
                  >
                    <span className="text-sm shrink-0">{info.icon}</span>
                    <span className={cn(
                      "flex-1 truncate",
                      isActive ? "text-gray-800 dark:text-gray-200 font-medium" : "text-gray-500 dark:text-gray-400"
                    )}>
                      {step.title || info.label}
                    </span>
                    {isDone && <CheckCircle2 size={11} className="text-green-400 shrink-0" />}
                    {isActive && <Loader2 size={11} className="text-blue-400 animate-spin shrink-0" />}
                    {step.timestamp && (
                      <span className="text-[10px] text-gray-300 dark:text-gray-600 tabular-nums shrink-0">
                        {new Date(step.timestamp).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Bottom bar — timeline with live indicator like Manus */}
      {isAgentActive && (
        <div className="shrink-0 border-t border-gray-100 dark:border-[#2a2d3a] px-4 py-2.5 flex items-center gap-3">
          <div className="flex-1 h-0.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-blue-500 rounded-full"
              animate={{ width: ["0%", "100%"] }}
              transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
            />
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] text-gray-500 font-medium">live</span>
          </div>
        </div>
      )}
    </div>
  );
}


function BudgetWarning() {
  const [dismissed, setDismissed] = useState(false);
  const spent = 1.24;
  const limit = 5.0;
  const pct = (spent / limit) * 100;
  const isWarning = pct >= 70;
  if (dismissed) return null;
  return (
    <div className={cn(
      "rounded-lg border p-3 space-y-2",
      isWarning ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <AlertTriangle size={12} className={isWarning ? "text-amber-500" : "text-gray-400"} />
          <span className={cn("text-xs font-semibold", isWarning ? "text-amber-700" : "text-gray-600")}>Бюджет задачи</span>
        </div>
        <button onClick={() => setDismissed(true)} className="text-gray-300 hover:text-gray-500 transition-colors">
          <X size={11} />
        </button>
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className={isWarning ? "text-amber-700 font-medium" : "text-gray-600"}>${spent.toFixed(2)} / ${limit.toFixed(2)}</span>
        <span className={cn("font-mono text-[10px]", isWarning ? "text-amber-600" : "text-gray-400")}>{Math.round(pct)}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
        <motion.div
          className={cn("h-1.5 rounded-full", isWarning ? "bg-amber-400" : "bg-indigo-400")}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      {isWarning && (
        <div className="text-[10px] text-amber-600">Использовано {Math.round(pct)}% бюджета. Задача продолжается.</div>
      )}
    </div>
  );
}

// ─── Iteration Counter ────────────────────────────────────────────────────────

function IterationCounter() {
  const iterations = [
    { n: 1, action: "Анализ задачи", tool: "Thinking", ms: 1800, status: "done" as const },
    { n: 2, action: "Поиск информации", tool: "Search", ms: 1400, status: "done" as const },
    { n: 3, action: "Генерация контента", tool: "AI", ms: 3200, status: "done" as const },
    { n: 4, action: "Создание лендинга", tool: "Code", ms: 0, status: "running" as const },
  ];
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Итерации агента</span>
        <span className="text-xs font-mono text-gray-500">{iterations.length} шагов</span>
      </div>
      <div className="space-y-1">
        {iterations.map(it => (
          <div key={it.n} className={cn(
            "flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs",
            it.status === "running" ? "bg-indigo-50 border border-indigo-100" : "bg-gray-50"
          )}>
            <span className={cn(
              "w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0",
              it.status === "done" ? "bg-green-100 text-green-600" : "bg-indigo-100 text-indigo-600"
            )}>{it.n}</span>
            <span className={cn("flex-1 truncate", it.status === "running" ? "text-indigo-800 font-medium" : "text-gray-600")}>{it.action}</span>
            <span className="text-[10px] text-gray-400 font-mono shrink-0">{it.tool}</span>
            {it.status === "done" && <span className="text-[10px] text-gray-400 font-mono shrink-0">{(it.ms / 1000).toFixed(1)}s</span>}
            {it.status === "running" && <Loader2 size={10} className="text-indigo-500 animate-spin shrink-0" />}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Browser Tab ─────────────────────────────────────────────────────────────

const BROWSER_PAGES = [
  {
    url: "https://arcaneai.ru/demo/preview",
    title: "ARCANE Preview",
    screenshot: null,
    status: "loading" as const,
    html: null,
  },
  {
    url: "https://getcomposer.org/download/",
    title: "Composer — Download",
    screenshot: null,
    status: "loaded" as const,
    html: `<div style="font-family:sans-serif;padding:20px;background:#fff">
      <h1 style="color:#2c3e50;font-size:24px;margin-bottom:8px">Composer</h1>
      <p style="color:#666;margin-bottom:16px">A Dependency Manager for PHP</p>
      <div style="background:#f8f9fa;border:1px solid #dee2e6;border-radius:6px;padding:16px;font-family:monospace;font-size:13px">
        <div style="color:#6c757d">// Download and install</div>
        <div style="color:#212529;margin-top:8px">php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"</div>
        <div style="color:#212529;margin-top:4px">php composer-setup.php</div>
        <div style="color:#212529;margin-top:4px">php -r "unlink('composer-setup.php');"</div>
      </div>
      <div style="margin-top:16px;padding:12px;background:#d4edda;border:1px solid #c3e6cb;border-radius:6px;color:#155724;font-size:13px">
        ✓ Composer 2.7.1 successfully installed
      </div>
    </div>`,
  },
  {
    url: "https://1c-bitrix.ru/download/cms.php",
    title: "Документация",
    screenshot: null,
    status: "loaded" as const,
    html: `<div style="font-family:sans-serif;padding:20px;background:#fff">
      <h1 style="color:#e31e24;font-size:20px;margin-bottom:4px">1С-Битрикс: Управление сайтом</h1>
      <p style="color:#666;font-size:13px;margin-bottom:16px">Версия 23.1100.0 · Дата выхода: 15.03.2024</p>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div style="flex:1;min-width:200px;border:1px solid #e0e0e0;border-radius:8px;padding:16px">
          <div style="font-weight:600;color:#333;margin-bottom:8px">Стандарт</div>
          <div style="font-size:13px;color:#666">Для малого бизнеса</div>
          <div style="margin-top:12px;padding:8px;background:#e8f4fd;border-radius:4px;font-size:12px;color:#1565c0">
            Загрузка: bitrix_23.1100.0.tar.gz (48 MB)
          </div>
        </div>
        <div style="flex:1;min-width:200px;border:2px solid #e31e24;border-radius:8px;padding:16px">
          <div style="font-weight:600;color:#e31e24;margin-bottom:8px">Бизнес ★</div>
          <div style="font-size:13px;color:#666">Для среднего бизнеса</div>
          <div style="margin-top:12px;padding:8px;background:#fde8e8;border-radius:4px;font-size:12px;color:#c62828">
            Загрузка: bitrix_business_23.1100.0.tar.gz (72 MB)
          </div>
        </div>
      </div>
    </div>`,
  },
];

function BrowserTab() {
  const [pageIndex, setPageIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isTakeover, setIsTakeover] = useState(false);
  const [novncReady, setNovncReady] = useState(false);
  const page = BROWSER_PAGES[pageIndex];

  const navigate = (idx: number) => {
    setIsLoading(true);
    setTimeout(() => {
      setPageIndex(idx);
      setIsLoading(false);
    }, 600);
  };

  const handleTakeover = () => {
    setIsTakeover(true);
    setNovncReady(false);
  };

  const handleReturnToAgent = () => {
    setIsTakeover(false);
    setNovncReady(false);
  };

  // noVNC URL — proxied through nginx /novnc/
  const novncUrl = `/novnc/vnc.html?autoconnect=1&reconnect=1&resize=scale&show_dot=1&path=novnc/websockify`;

  return (
    <div className="flex flex-col h-full">
      {/* Takeover banner */}
      {isTakeover && (
        <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-3 py-2 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse shrink-0" />
          <Monitor size={12} className="text-amber-600 shrink-0" />
          <span className="text-[11px] font-semibold text-amber-800 flex-1">Режим управления браузером</span>
          <button
            onClick={handleReturnToAgent}
            className="flex items-center gap-1 px-2 py-1 rounded bg-amber-200 text-amber-800 text-[10px] font-medium hover:bg-amber-300 transition-colors"
          >
            <X size={9} />
            Вернуть агенту
          </button>
        </div>
      )}

      {/* Browser chrome (only in normal mode) */}
      {!isTakeover && (
        <div className="shrink-0 border-b border-gray-100 bg-gray-50 px-3 py-2 space-y-2">
          {/* Navigation bar */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => pageIndex > 0 && navigate(pageIndex - 1)}
              disabled={pageIndex === 0}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 transition-colors"
            >
              <ArrowLeft size={12} className="text-gray-600" />
            </button>
            <button
              onClick={() => pageIndex < BROWSER_PAGES.length - 1 && navigate(pageIndex + 1)}
              disabled={pageIndex === BROWSER_PAGES.length - 1}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-30 transition-colors"
            >
              <ArrowRight size={12} className="text-gray-600" />
            </button>
            <button
              onClick={() => navigate(pageIndex)}
              className="p-1 rounded hover:bg-gray-200 transition-colors"
            >
              <RefreshCw size={12} className={cn("text-gray-600", isLoading && "animate-spin")} />
            </button>
            {/* URL bar */}
            <div className="flex-1 flex items-center gap-1.5 bg-white border border-gray-200 rounded-md px-2 py-1">
              <Lock size={10} className="text-green-500 shrink-0" />
              <span className="text-[11px] text-gray-600 font-mono truncate flex-1">{page.url}</span>
            </div>
            {/* Takeover button */}
            <button
              onClick={handleTakeover}
              className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-600 text-white text-[10px] font-medium hover:bg-indigo-700 transition-colors shrink-0"
              title="Перехватить управление браузером"
            >
              <Monitor size={10} />
              Управлять
            </button>
          </div>
          {/* Page tabs */}
          <div className="flex items-center gap-1 overflow-x-auto">
            {BROWSER_PAGES.map((p, i) => (
              <button
                key={i}
                onClick={() => navigate(i)}
                className={cn(
                  "flex items-center gap-1.5 px-2 py-1 rounded text-[10px] whitespace-nowrap transition-colors shrink-0",
                  i === pageIndex ? "bg-white border border-gray-200 text-gray-700 shadow-sm" : "text-gray-500 hover:bg-gray-100"
                )}
              >
                <Globe size={9} />
                <span className="max-w-[80px] truncate">{p.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Page content */}
      <div className="flex-1 overflow-hidden bg-white relative">
        {isTakeover ? (
          /* noVNC iframe — interactive browser control */
          <div className="w-full h-full relative">
            {!novncReady && (
              <div className="absolute inset-0 flex items-center justify-center bg-gray-900 z-10">
                <div className="flex flex-col items-center gap-3 text-center">
                  <Loader2 size={24} className="text-indigo-400 animate-spin" />
                  <span className="text-sm text-gray-300">Подключение к браузеру...</span>
                  <span className="text-xs text-gray-500">noVNC — интерактивное управление</span>
                </div>
              </div>
            )}
            <iframe
              src={novncUrl}
              className="w-full h-full border-0"
              allow="clipboard-read; clipboard-write"
              onLoad={() => setNovncReady(true)}
              title="Browser Takeover — noVNC"
            />
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-3">
              <Loader2 size={20} className="text-indigo-500 animate-spin" />
              <span className="text-xs text-gray-500">Загрузка страницы...</span>
              <div className="w-48 h-1 bg-gray-100 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-indigo-500 rounded-full"
                  initial={{ width: "0%" }}
                  animate={{ width: "100%" }}
                  transition={{ duration: 0.6, ease: "easeInOut" }}
                />
              </div>
            </div>
          </div>
        ) : page.html ? (
          <div className="p-3 h-full overflow-auto">
            <div className="text-[10px] text-gray-400 mb-2 flex items-center gap-1.5">
              <Monitor size={10} />
              Предпросмотр страницы (симуляция)
            </div>
            <div
              className="border border-gray-100 rounded-lg overflow-hidden"
              dangerouslySetInnerHTML={{ __html: page.html }}
            />
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-2 text-center px-4">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center">
                <Globe size={18} className="text-indigo-400" />
              </div>
              <div className="text-xs font-medium text-gray-700">Агент открывает страницу</div>
              <div className="text-[11px] text-gray-400 font-mono">{page.url}</div>
              <div className="flex items-center gap-1.5 mt-1">
                <Loader2 size={11} className="text-indigo-400 animate-spin" />
                <span className="text-[11px] text-gray-400">Ожидание ответа сервера...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="shrink-0 border-t border-gray-100 bg-gray-50 px-3 py-1.5 flex items-center gap-3">
        {isTakeover ? (
          <>
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span className="text-[10px] font-medium text-green-600">Интерактивное управление</span>
            <span className="text-[10px] text-gray-400 ml-auto">noVNC · порт 6080</span>
          </>
        ) : (
          <>
            <span className={cn(
              "text-[10px] font-medium",
              isLoading ? "text-amber-600" : page.status === "loaded" ? "text-green-600" : "text-gray-500"
            )}>
              {isLoading ? "Загрузка..." : page.status === "loaded" ? "Готово" : "Ожидание..."}
            </span>
            <span className="text-[10px] text-gray-400 ml-auto">Страница {pageIndex + 1} из {BROWSER_PAGES.length}</span>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Steps Tab ───────────────────────────────────────────────────────────────

function StepsTab({ activeStep, onStepSelect, steps }: {
  activeStep?: string;
  onStepSelect: (id: string) => void;
  steps?: Step[];
}) {
  const [expandedStep, setExpandedStep] = useState<string | null>(activeStep ?? null);

  useEffect(() => {
    if (activeStep) setExpandedStep(activeStep);
  }, [activeStep]);

  const displaySteps = steps ?? [];

  const handleToggle = (id: string) => {
    setExpandedStep(expandedStep === id ? null : id);
    onStepSelect(id);
  };

  if (displaySteps.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-gray-400">
        Нет шагов для этого чата
      </div>
    );
  }

  return (
    <div className="p-3 space-y-1.5">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-1 pb-1">
        Execution Timeline · {displaySteps.length} шагов
      </div>
      {displaySteps.map((step, index) => (
        <StepRow
          key={step.id}
          step={step}
          index={index}
          expanded={expandedStep === step.id}
          active={activeStep === step.id}
          onToggle={() => handleToggle(step.id)}
        />
      ))}
    </div>
  );
}

function StepRow({ step, index, expanded, active, onToggle }: {
  step: Step; index: number; expanded: boolean; active: boolean; onToggle: () => void;
}) {
  const statusIcon = {
    success: <CheckCircle2 size={14} className="text-green-500" />,
    failed:  <XCircle size={14} className="text-red-500" />,
    warning: <AlertTriangle size={14} className="text-amber-500" />,
    running: <Loader2 size={14} className="text-blue-500 animate-spin" />,
    queued:  <Clock size={14} className="text-gray-400" />,
    skipped: <X size={14} className="text-gray-300" />,
    partial: <AlertTriangle size={14} className="text-amber-500" />,
  }[step.status] ?? <Clock size={14} className="text-gray-400" />;

  const toolIcon = {
    SSH: <Terminal size={11} />,
    Terminal: <Terminal size={11} />,
    Browser: <Globe size={11} />,
    Search: <Search size={11} />,
  }[step.tool] ?? <Terminal size={11} />;

  return (
    <div className={cn(
      "rounded-lg border transition-all",
      active ? "border-indigo-200 bg-indigo-50/50" : "border-gray-100 bg-white hover:border-gray-200",
    )}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left"
      >
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[10px] text-gray-400 font-mono w-4 text-right">{index + 1}</span>
          {statusIcon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-gray-800 truncate">{step.title}</span>
            {step.goldenPath && <Star size={10} className="text-amber-500 shrink-0" fill="currentColor" />}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="inline-flex items-center gap-1 text-[10px] text-gray-400">
              {toolIcon} {step.tool}
            </span>
            <span className="text-[10px] text-gray-400">{step.startTime}</span>
            {step.duration !== "..." && (
              <span className="text-[10px] font-mono text-gray-400">{step.duration}</span>
            )}
          </div>
        </div>
        {expanded ? <ChevronDown size={13} className="text-gray-400 shrink-0" /> : <ChevronRight size={13} className="text-gray-400 shrink-0" />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2 border-t border-gray-100 pt-2">
              <div className="text-xs text-gray-600">{typeof step.summary === "string" ? step.summary : JSON.stringify(step.summary)}</div>

              {step.args && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1">Аргументы</div>
                  <div className="bg-gray-900 rounded-md p-2 font-mono text-[11px] text-green-400 space-y-0.5">
                    {Object.entries(step.args).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-gray-500">{k}: </span>
                        <span>{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {step.result && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1">Результат</div>
                  <div className="text-xs text-gray-700 bg-green-50 border border-green-100 rounded-md p-2 whitespace-pre-wrap break-all">
                    {typeof step.result === "string" ? step.result : JSON.stringify(step.result, null, 2)}
                  </div>
                </div>
              )}

              {step.warning && (
                <div className="flex items-start gap-1.5 p-2 bg-amber-50 border border-amber-100 rounded-md">
                  <AlertTriangle size={12} className="text-amber-500 shrink-0 mt-0.5" />
                  <span className="text-xs text-amber-700">{step.warning}</span>
                </div>
              )}

              {step.goldenPath && (
                <div className="flex items-center gap-1.5 text-[11px] text-amber-600">
                  <Star size={11} fill="currentColor" />
                  Использован golden path
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Logs Tab ────────────────────────────────────────────────────────────────

function LogsTab({ steps, logs }: { steps?: Step[]; logs?: LogEntry[] }) {
  const [filter, setFilter] = useState<string>("all");

  const levelConfig: Record<string, { bg: string; text: string; label: string }> = {
    info:     { bg: "bg-gray-50 dark:bg-gray-900",   text: "text-gray-600 dark:text-gray-400",  label: "INFO" },
    warn:     { bg: "bg-amber-50 dark:bg-amber-950",  text: "text-amber-700 dark:text-amber-400", label: "WARN" },
    error:    { bg: "bg-red-50 dark:bg-red-950",    text: "text-red-700 dark:text-red-400",   label: "ERR" },
    tool:     { bg: "bg-blue-50 dark:bg-blue-950",   text: "text-blue-700 dark:text-blue-400",  label: "TOOL" },
    verifier: { bg: "bg-green-50 dark:bg-green-950",  text: "text-green-700 dark:text-green-400", label: "VRF" },
    judge:    { bg: "bg-purple-50 dark:bg-purple-950", text: "text-purple-700 dark:text-purple-400",label: "JDG" },
  };

  // Convert steps to log entries if no real logs provided
  const derivedLogs: LogEntry[] = logs && logs.length > 0 ? logs : (steps || []).map((s, i) => ({
    id: s.id || `log_${i}`,
    time: s.startTime ? new Date(s.startTime).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "",
    level: s.status === "failed" ? "error" : s.status === "warning" ? "warn" : (s.tool ? "tool" : "info") as LogEntry["level"],
    message: s.tool ? `[${s.tool}] ${s.title}${s.result ? " → " + s.result : ""}` : s.title,
  }));

  const filtered = filter === "all" ? derivedLogs : derivedLogs.filter(l => l.level === filter);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-100 flex-wrap shrink-0">
        {["all", "tool", "verifier", "warn", "error"].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "px-2 py-0.5 rounded text-[11px] font-medium transition-colors",
              filter === f ? "bg-indigo-100 text-indigo-700" : "text-gray-500 hover:bg-gray-100"
            )}
          >
            {f === "all" ? "Все" : f.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5 font-mono">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full min-h-[120px] text-center py-8">
            <ScrollText size={20} className="text-gray-300 dark:text-gray-600 mb-2" />
            <div className="text-xs text-gray-400 dark:text-gray-500">
              {derivedLogs.length === 0 ? "Логи появятся во время выполнения задачи" : "Нет записей для выбранного фильтра"}
            </div>
          </div>
        ) : filtered.map(entry => {
          const cfg = levelConfig[entry.level] ?? levelConfig.info;
          return (
            <div key={entry.id} className={cn("flex items-start gap-2 px-2 py-1 rounded text-[11px]", cfg.bg)}>
              <span className="text-gray-400 dark:text-gray-500 shrink-0 w-14">{entry.time}</span>
              <span className={cn("shrink-0 font-semibold w-8", cfg.text)}>{cfg.label}</span>
              <span className="text-gray-700 dark:text-gray-300 break-all">{entry.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Files Tab ───────────────────────────────────────────────────────────────

const FILE_PREVIEWS: Record<string, { lang: string; code: string }> = {
  "nginx.conf": {
    lang: "nginx",
    code: `server {
    listen 80;
    server_name example.com www.example.com;
    root /var/www/bitrix/public_html;
    index index.php;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \\.php$ {
        fastcgi_pass unix:/var/run/php/php8.2-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Bitrix specific
    location ~* ^/bitrix/admin/ {
        allow 185.22.0.0/16;
        deny all;
    }
}`,
  },
  "install.log": {
    lang: "log",
    code: `[2024-03-15 14:32:01] INFO  Starting Bitrix installation
[2024-03-15 14:32:03] INFO  PHP 8.2.0 detected ✓
[2024-03-15 14:32:03] INFO  MySQL 8.0.32 detected ✓
[2024-03-15 14:32:05] INFO  Downloading bitrix_23.1100.0.tar.gz (48 MB)
[2024-03-15 14:33:21] INFO  Download complete
[2024-03-15 14:33:22] INFO  Extracting archive...
[2024-03-15 14:33:45] INFO  Extraction complete
[2024-03-15 14:33:46] INFO  Running composer install
[2024-03-15 14:34:12] INFO  Dependencies installed (247 packages)
[2024-03-15 14:34:13] INFO  Configuring database connection
[2024-03-15 14:34:14] INFO  Database 'bitrix_db' created ✓
[2024-03-15 14:34:15] INFO  Running migrations...
[2024-03-15 14:35:02] INFO  Migrations complete (142 tables)
[2024-03-15 14:35:03] SUCCESS Installation complete`,
  },
  "setup.php": {
    lang: "php",
    code: `<?php
// Bitrix Database Configuration
define('DB_HOST', 'localhost');
define('DB_NAME', 'bitrix_db');
define('DB_USER', 'bitrix_user');
define('DB_PASS', '***');

// Site settings
define('SITE_URL', 'https://example.com');
define('ADMIN_EMAIL', 'admin@example.com');

// Performance
define('BX_CACHE_TYPE', 'memcache');
define('BX_CACHE_SID', 'bitrix');
define('BX_MEMCACHE_HOST', '127.0.0.1');
define('BX_MEMCACHE_PORT', '11211');

// Security
define('BX_SECURITY_TOKEN', bin2hex(random_bytes(32)));
define('BX_ADMIN_IP_WHITELIST', ['185.22.0.0/16']);`,
  },
};

function FilesTab({ steps }: { steps?: Step[] }) {
  // Build file list from steps that have artifacts or results
  const realArtifacts: MockArtifact[] = (steps || []).filter(s => s.result || s.args).map((s, i) => ({
    id: s.id || `file_${i}`,
    name: s.args?.filename || s.args?.path || s.args?.file || `${s.tool || 'file'}_${i}.txt`,
    type: (s.tool === 'file_write' || s.tool === 'file_create' || s.tool === 'file_edit') ? 'code' : 'document',
    size: s.result ? `${Math.ceil(s.result.length / 1024)}KB` : undefined,
    createdAt: s.startTime ? new Date(s.startTime).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) : '',
  }));
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState<{ name: string; progress: number }[]>([]);

  const typeIcon: Record<string, React.ReactNode> = {
    code:     <FileCode size={14} className="text-blue-500" />,
    document: <FileText size={14} className="text-gray-500" />,
    image:    <ImageIcon size={14} className="text-green-500" />,
    report:   <FileText size={14} className="text-purple-500" />,
    site:     <Globe size={14} className="text-indigo-500" />,
    html:     <FileCode size={14} className="text-orange-500" />,
  };

  const handleCopy = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const simulateUpload = () => {
    const name = `file_${Date.now()}.txt`;
    setUploadingFiles(prev => [...prev, { name, progress: 0 }]);
    let progress = 0;
    const interval = setInterval(() => {
      progress += Math.random() * 20 + 5;
      if (progress >= 100) {
        progress = 100;
        clearInterval(interval);
        setTimeout(() => {
          setUploadingFiles(prev => prev.filter(f => f.name !== name));
        }, 800);
      }
      setUploadingFiles(prev => prev.map(f => f.name === name ? { ...f, progress: Math.min(progress, 100) } : f));
    }, 200);
  };

  if (previewFile) {
    const preview = FILE_PREVIEWS[previewFile];
    return (
      <div className="flex flex-col h-full">
        {/* Preview header */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
          <button
            onClick={() => setPreviewFile(null)}
            className="p-1 rounded hover:bg-gray-200 transition-colors"
          >
            <ArrowLeft size={13} className="text-gray-600" />
          </button>
          <Code2 size={13} className="text-gray-500" />
          <span className="text-xs font-medium text-gray-700 flex-1">{previewFile}</span>
          <button
            onClick={() => preview && handleCopy(preview.code)}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] hover:bg-gray-200 transition-colors text-gray-500"
          >
            {copied ? <Check size={11} className="text-green-500" /> : <Copy size={11} />}
            {copied ? "Скопировано" : "Копировать"}
          </button>
        </div>
        {/* Code content */}
        <div className="flex-1 overflow-auto bg-gray-900 p-4">
          {preview ? (
            <pre className="font-mono text-[11px] text-green-300 leading-relaxed whitespace-pre-wrap">
              <code>{preview.code}</code>
            </pre>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              Предпросмотр недоступен
            </div>
          )}
        </div>
        {/* Lang badge */}
        <div className="shrink-0 border-t border-gray-700 bg-gray-800 px-3 py-1.5">
          <span className="text-[10px] text-gray-400 font-mono uppercase">{preview?.lang ?? "text"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-1.5">
      <div className="flex items-center justify-between px-1 pb-1">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Созданные файлы</span>
        <button
          onClick={simulateUpload}
          className="text-[10px] text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
        >
          + Загрузить файл
        </button>
      </div>

      {/* Uploading files */}
      <AnimatePresence>
        {uploadingFiles.map(f => (
          <motion.div
            key={f.name}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2.5 p-2.5 rounded-lg border border-indigo-100 bg-indigo-50"
          >
            <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0">
              <Loader2 size={14} className="text-indigo-500 animate-spin" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-indigo-800 truncate">{f.name}</div>
              <div className="mt-1 w-full bg-indigo-100 rounded-full h-1">
                <motion.div
                  className="bg-indigo-500 h-1 rounded-full"
                  animate={{ width: `${f.progress}%` }}
                  transition={{ duration: 0.2 }}
                />
              </div>
              <div className="text-[10px] text-indigo-500 mt-0.5">{Math.round(f.progress)}%</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>

      {realArtifacts.length === 0 && uploadingFiles.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <FolderOpen size={20} className="text-gray-300 dark:text-gray-600 mb-2" />
          <div className="text-xs text-gray-400 dark:text-gray-500">Файлы появятся когда агент создаст их</div>
        </div>
      )}
      {realArtifacts.map(artifact => (
        <div
          key={artifact.id}
          className="flex items-center gap-2.5 p-2.5 rounded-lg border border-gray-100 bg-white hover:border-indigo-200 hover:bg-indigo-50/30 transition-colors group cursor-pointer"
          onClick={() => FILE_PREVIEWS[artifact.name] && setPreviewFile(artifact.name)}
        >
          <div className="w-8 h-8 rounded-lg bg-gray-50 border border-gray-100 flex items-center justify-center shrink-0">
            {typeIcon[artifact.type] ?? <FileText size={14} className="text-gray-400" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium text-gray-800 truncate">{artifact.name}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] text-gray-400 uppercase">{artifact.type}</span>
              {artifact.size && <span className="text-[10px] text-gray-400">{artifact.size}</span>}
              <span className="text-[10px] text-gray-400">{artifact.createdAt}</span>
            </div>
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {FILE_PREVIEWS[artifact.name] && (
              <button
                className="p-1 rounded hover:bg-indigo-100 text-indigo-400 hover:text-indigo-600"
                onClick={e => { e.stopPropagation(); setPreviewFile(artifact.name); }}
              >
                <Eye size={12} />
              </button>
            )}
            <button
              className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
              onClick={e => e.stopPropagation()}
            >
              <Download size={12} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Verify Tab ──────────────────────────────────────────────────────────────

function VerifyTab() {
  return (
    <div className="p-3 space-y-3">
      <div className="rounded-xl border border-green-200 bg-green-50 p-3">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle2 size={14} className="text-green-600" />
          <span className="text-xs font-semibold text-green-800">Verifier</span>
          <span className="ml-auto text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">Пройдено</span>
        </div>
        <div className="space-y-1.5">
          {[
            { label: "PHP 8.2 установлен", ok: true },
            { label: "MySQL 8+ доступен", ok: true },
            { label: "Bitrix файлы загружены", ok: true },
            { label: "Административная панель", ok: null },
          ].map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-green-800">
              {item.ok === true && <CheckCircle2 size={11} className="text-green-500 shrink-0" />}
              {item.ok === false && <XCircle size={11} className="text-red-500 shrink-0" />}
              {item.ok === null && <Loader2 size={11} className="text-blue-500 animate-spin shrink-0" />}
              {item.label}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-3">
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck size={14} className="text-indigo-600" />
          <span className="text-xs font-semibold text-indigo-800">Judge</span>
          <span className="ml-auto text-xs font-medium text-indigo-700 bg-indigo-100 px-2 py-0.5 rounded-full">Ожидает</span>
        </div>
        <div className="text-xs text-indigo-700">
          Ожидает завершения шага 5 для финальной оценки качества.
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck size={14} className="text-gray-500" />
          <span className="text-xs font-semibold text-gray-700">Safety</span>
          <span className="ml-auto text-xs font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full border border-green-200">OK</span>
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs text-gray-600">
            <Star size={10} className="text-amber-500" fill="currentColor" />
            <span>Golden path: <span className="font-medium text-amber-700">bitrix-standard-install-v2</span></span>
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <CheckCircle2 size={10} className="text-green-500" />
            Anti-patterns: не обнаружено
          </div>
        </div>
      </div>

      {/* Anti-patterns block */}
      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={14} className="text-gray-400" />
          <span className="text-xs font-semibold text-gray-700">Anti-patterns</span>
          <span className="ml-auto text-xs text-gray-400">0 найдено</span>
        </div>
        <div className="space-y-1.5">
          {[
            { label: "Прямое удаление файлов без бэкапа", blocked: true, triggered: false },
            { label: "Запуск команд от root без sudo", blocked: true, triggered: false },
            { label: "Открытие портов без firewall", blocked: false, triggered: false },
          ].map((ap, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <div className={cn(
                "w-1.5 h-1.5 rounded-full shrink-0",
                ap.triggered ? "bg-red-500" : "bg-gray-200"
              )} />
              <span className={ap.triggered ? "text-red-700 font-medium" : "text-gray-400 line-through"}>{ap.label}</span>
              {ap.blocked && (
                <span className="ml-auto text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">заблокировано</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Result Tab ──────────────────────────────────────────────────────────────

function ResultTab() {
  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-2 p-3 rounded-xl bg-amber-50 border border-amber-200">
        <Clock size={14} className="text-amber-600" />
        <span className="text-xs text-amber-700 font-medium">Задача ещё выполняется</span>
      </div>

      <div className="p-3 rounded-xl border border-gray-200 bg-white space-y-2">
        <div className="text-xs font-semibold text-gray-700">Что уже сделано</div>
        {[
          "Сервер проверен, PHP 8.2 установлен",
          "Зависимости установлены",
          "Bitrix installer загружен и запущен",
          "База данных настроена",
        ].map((item, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-gray-600">
            <CheckCircle2 size={11} className="text-green-500 shrink-0" />
            {item}
          </div>
        ))}
      </div>

      <div className="p-3 rounded-xl border border-gray-200 bg-white space-y-2">
        <div className="text-xs font-semibold text-gray-700">Осталось</div>
        {[
          "Проверить административную панель",
          "Настроить SSL сертификат",
        ].map((item, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-gray-500">
            <Circle size={11} className="text-gray-300 shrink-0" />
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}