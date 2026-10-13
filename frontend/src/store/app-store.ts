import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AgentStep, AnswerDetail, AnswerSummary, ChatCitation, QualityReport, RoutingInfo } from '@/lib/api/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: ChatCitation[]
  agentSteps?: AgentStep[]
  quality?: QualityReport
  routing?: RoutingInfo | null
  councilRunId?: string | null
  reportId?: string
  /** Known as soon as the answer finishes, before scoring. */
  summary?: AnswerSummary
  /** What was asked for, shown while the answer is still being produced. */
  pendingStrategy?: string
  pendingDetail?: AnswerDetail
  stage?: string
  errored?: boolean
  errorCode?: string
  streaming?: boolean
  scoring?: boolean
}

/** Every answer is quick (3–4 lines) unless Deep reasoning is switched on (7–8 lines). */
export type DetailMode = AnswerDetail

/**
 * State shared across tabs. The document selection and the answer-length preference are
 * persisted; a document id only ever comes from a real backend response and is re-validated
 * on load (app-shell.tsx). The conversation lives here, not in the Workspace page, so
 * switching tabs does not lose it — it is kept per document and saved in the browser, so a
 * reload or a return to an earlier document shows the same history.
 */
interface AppStore {
  documentId: string | null
  documentName: string | null
  sessionId: string | null
  lastReportId: string | null
  /** Report shown in the Workspace analysis panel; null = the latest one. */
  focusedReportId: string | null
  detailMode: DetailMode
  /** A strategy chosen for upcoming questions; null = use the workspace default. */
  strategyOverride: string | null
  conversations: Record<string, ChatMessage[]>
  setDocument: (id: string | null, name: string | null) => void
  setSession: (id: string | null) => void
  setLastReportId: (id: string | null) => void
  setFocusedReportId: (id: string | null) => void
  setDetailMode: (mode: DetailMode) => void
  setStrategyOverride: (id: string | null) => void
  appendMessages: (documentId: string, messages: ChatMessage[]) => void
  updateMessage: (documentId: string, messageId: string, update: (m: ChatMessage) => ChatMessage) => void
  clearConversation: (documentId: string) => void
}

const MAX_MESSAGES_PER_DOCUMENT = 80
const MAX_DOCUMENTS_WITH_HISTORY = 25

/** What is kept across reloads: the most recent messages of the most recently used documents.
 * Answers and their report ids are real backend output; nothing is reconstructed. */
function trimHistory(conversations: Record<string, ChatMessage[]>): Record<string, ChatMessage[]> {
  const entries = Object.entries(conversations).filter(([, messages]) => messages.length > 0)
  return Object.fromEntries(entries.slice(-MAX_DOCUMENTS_WITH_HISTORY).map(([id, messages]) => [id, messages.slice(-MAX_MESSAGES_PER_DOCUMENT)]))
}

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      documentId: null,
      documentName: null,
      sessionId: null,
      lastReportId: null,
      focusedReportId: null,
      detailMode: 'brief',
      strategyOverride: null,
      conversations: {},
      setDocument: (id, name) =>
        set((state) =>
          state.documentId === id
            ? { documentName: name }
            : { documentId: id, documentName: name, sessionId: null, lastReportId: null, focusedReportId: null, strategyOverride: null },
        ),
      setSession: (id) => set({ sessionId: id }),
      setLastReportId: (id) => set({ lastReportId: id }),
      setFocusedReportId: (id) => set({ focusedReportId: id }),
      setDetailMode: (mode) => set({ detailMode: mode }),
      setStrategyOverride: (id) => set({ strategyOverride: id }),
      appendMessages: (documentId, messages) =>
        set((state) => ({
          conversations: { ...state.conversations, [documentId]: [...(state.conversations[documentId] ?? []), ...messages] },
        })),
      updateMessage: (documentId, messageId, update) =>
        set((state) => ({
          conversations: {
            ...state.conversations,
            [documentId]: (state.conversations[documentId] ?? []).map((m) => (m.id === messageId ? update(m) : m)),
          },
        })),
      clearConversation: (documentId) =>
        set((state) => {
          const next = { ...state.conversations }
          delete next[documentId]
          return { conversations: next, sessionId: null, lastReportId: null, focusedReportId: null }
        }),
    }),
    {
      name: 'veritas:workspace',
      partialize: (state) => ({
        documentId: state.documentId,
        documentName: state.documentName,
        detailMode: state.detailMode,
        conversations: trimHistory(state.conversations),
      }),
      // A reply that was mid-stream when the page closed is over; never show it as pending.
      onRehydrateStorage: () => (state) => {
        if (!state) return
        if (state.detailMode !== 'deep') state.detailMode = 'brief' // older builds stored "auto"
        for (const messages of Object.values(state.conversations)) {
          for (const m of messages) {
            if (m.streaming && !m.content) {
              m.content = 'This answer was interrupted when the page closed.'
              m.errored = true
            }
            m.streaming = false
            m.scoring = false
            m.stage = undefined
          }
        }
      },
    },
  ),
)
