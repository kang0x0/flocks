/**
 * SessionViewDialog — 查看已有 LLM 会话的弹出对话框
 *
 * 用于 Cairn 详情页等场景，直接查看已存在的 session 的消息历史。
 * 与 ChatDialog 不同：ChatDialog 创建新会话并发送 prompt，
 * 本组件直接展示已有 session。
 */
import { X, MessageCircle } from 'lucide-react';
import SessionChat from './SessionChat';

interface SessionViewDialogProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  title: string;
  subtitle?: string;
  live?: boolean;
}

export default function SessionViewDialog({
  open,
  onClose,
  sessionId,
  title,
  subtitle,
  live = false,
}: SessionViewDialogProps) {

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl mx-4 flex flex-col"
        style={{ height: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 flex-shrink-0 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-red-500 to-purple-600 flex items-center justify-center shrink-0">
              <MessageCircle className="w-5 h-5 text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-slate-800 truncate">{title}</h2>
              {subtitle && <p className="text-xs text-slate-400 mt-0.5 truncate">{subtitle}</p>}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-2 rounded-lg hover:bg-slate-100 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 rounded-b-2xl overflow-hidden flex flex-col">
          <SessionChat
            key={sessionId}
            sessionId={sessionId}
            live={live}
            hideInput={true}
            display={{ compact: false, showActions: true, showTimestamp: true }}
          />
        </div>
      </div>
    </div>
  );
}
