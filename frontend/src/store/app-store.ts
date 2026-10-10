import { create } from 'zustand'

/** The one piece of state every tab needs: which document (and chat session) the user is
 * currently working with. Set once in the Workspace after a real upload/ingest or chat turn;
 * read everywhere else (Dashboard, Architecture, Knowledge Graph, Evaluation). Not persisted —
 * a fresh document_id/session_id only ever comes from a real backend response. */
interface AppStore {
  documentId: string | null
  documentName: string | null
  sessionId: string | null
  lastReportId: string | null
  setDocument: (id: string | null, name: string | null) => void
  setSession: (id: string | null) => void
  setLastReportId: (id: string | null) => void
}

export const useAppStore = create<AppStore>((set) => ({
  documentId: null,
  documentName: null,
  sessionId: null,
  lastReportId: null,
  setDocument: (id, name) => set({ documentId: id, documentName: name }),
  setSession: (id) => set({ sessionId: id }),
  setLastReportId: (id) => set({ lastReportId: id }),
}))
