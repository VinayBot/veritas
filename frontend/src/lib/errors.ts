import { ApiError } from '@/lib/api/types'

export interface ExplainedError {
  title: string
  /** What happened, in plain English. */
  explanation: string
  /** What the reader can do about it, when there is something. */
  fix?: string
  /** The actual error text, unedited. */
  raw: string
}

const BY_CODE: Record<string, Omit<ExplainedError, 'raw'>> = {
  ollama_unreachable: {
    title: 'Ollama is not running',
    explanation: 'The local model server did not answer, so nothing that needs a language model can run.',
    fix: 'Start it with `ollama serve` (or open the Ollama app), then try again.',
  },
  llm_unavailable: {
    title: 'The language model did not answer',
    explanation: 'The model call failed or timed out.',
    fix: 'Check that Ollama is running and the selected model is pulled (`ollama list`).',
  },
  document_not_found: {
    title: 'That document no longer exists',
    explanation: 'It may have been deleted, or the local data folder was reset.',
    fix: 'Pick another document from the switcher, or upload it again.',
  },
  document_not_ready: {
    title: 'The document is still being ingested',
    explanation: 'It has not finished parsing and indexing yet.',
    fix: 'Wait for its status to turn ready in Workspace.',
  },
  dataset_empty: {
    title: 'No evaluation questions could be generated',
    explanation: 'The document has no indexed chunks, or the model that writes the questions is unavailable.',
    fix: 'Check the document finished ingesting and that Ollama is running.',
  },
  index_mismatch: {
    title: 'The index was built with a different embedding model',
    explanation: 'Searching it with the current embedding model would return unrelated results, so the request was stopped.',
    fix: 'Re-index the document from Settings → Models.',
  },
  strategy_unavailable: {
    title: 'That RAG strategy cannot run yet',
    explanation: 'Something it depends on is missing for this document.',
    fix: 'Open the strategy picker to see what is missing and build it.',
  },
  unsupported_format: {
    title: 'That file type is not supported',
    explanation: 'No parser is registered for this extension.',
    fix: 'Use PDF, DOCX, PPTX, XLSX, HTML, Markdown, TXT, CSV, EML, RTF, or legacy DOC/XLS.',
  },
  file_too_large: {
    title: 'That file is too large',
    explanation: 'Uploads are limited to 25 MB.',
  },
  invalid_model_selection: {
    title: 'That model cannot be used for this role',
    explanation: 'The selected model is not installed or does not support the role you picked it for.',
    fix: 'Choose a model listed for that role in the picker.',
  },
}

export function explainError(error: unknown): ExplainedError {
  if (error instanceof ApiError) {
    const known = BY_CODE[error.code]
    return {
      title: known?.title ?? 'The request failed',
      explanation: known?.explanation ?? 'The backend rejected or could not complete this request.',
      fix: known?.fix,
      raw: `${error.code}: ${error.message}`,
    }
  }
  const raw = error instanceof Error ? error.message : String(error)
  if (/failed to fetch|networkerror|load failed/i.test(raw)) {
    return {
      title: 'The backend is unreachable',
      explanation: 'The browser could not connect to the Veritas API.',
      fix: 'Start it with `make backend-dev` from the repo root, then reload.',
      raw,
    }
  }
  return {
    title: 'Something went wrong',
    explanation: 'An unexpected error occurred.',
    raw,
  }
}
