import { create } from 'zustand'
import { getModels, resetModelSelection, setModelSelection } from '@/lib/api/client'
import type { ModelSelection, ModelsState } from '@/lib/api/types'

/** One copy of "which models are installed and selected", shared by the Workspace picker and
 * the Settings dialog so a change in one is immediately visible in the other. */
interface ModelsStore {
  state: ModelsState | null
  error: unknown
  loading: boolean
  load: () => Promise<void>
  apply: (changes: Partial<Omit<ModelSelection, 'guard'>>) => Promise<ModelsState>
  reset: () => Promise<void>
}

export const useModelsStore = create<ModelsStore>((set) => ({
  state: null,
  error: null,
  loading: false,
  load: async () => {
    set({ loading: true })
    try {
      set({ state: await getModels(), error: null, loading: false })
    } catch (error) {
      set({ error, loading: false })
    }
  },
  apply: async (changes) => {
    const state = await setModelSelection(changes)
    set({ state, error: null })
    return state
  },
  reset: async () => {
    set({ state: await resetModelSelection(), error: null })
  },
}))
