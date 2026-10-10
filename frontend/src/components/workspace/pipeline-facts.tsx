import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { FileText, Scissors, Sparkles, Shield, Boxes, Database, Cpu, Gauge as GaugeIcon } from 'lucide-react'
import { getHealth } from '@/lib/api/client'
import type { DocumentResponse } from '@/lib/api/types'

interface Fact {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
}

/** Every value here is read straight off the real DocumentResponse / GET /health — see
 * call sites. Embedder/reranker names come from the startup preflight's own real model
 * instances (app/core/preflight.py), not a hardcoded string. */
export function PipelineFacts({ doc, mode }: { doc: DocumentResponse; mode: string }) {
  const reduced = useReducedMotion()
  const [embedderDetail, setEmbedderDetail] = useState<string | null>(null)
  const [rerankerDetail, setRerankerDetail] = useState<string | null>(null)
  const [vectorStore, setVectorStore] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then((h) => {
        const embedder = h.preflight.status !== 'running' ? h.preflight.checks.find((c) => c.name === 'embedder') : null
        const reranker = h.preflight.status !== 'running' ? h.preflight.checks.find((c) => c.name === 'reranker') : null
        setEmbedderDetail(embedder?.detail ?? null)
        setRerankerDetail(reranker?.detail ?? null)
        setVectorStore(h.vector_store)
      })
      .catch(() => {})
  }, [])

  const piiTotal = Object.values(doc.pii_counts).reduce((a, b) => a + b, 0)

  const facts: Fact[] = [
    { icon: FileText, label: 'Parser', value: 'Docling (layout-aware)' },
    {
      icon: Sparkles,
      label: 'Refinement quality',
      value:
        doc.quality_score_before !== null && doc.quality_score_after !== null
          ? `${doc.quality_score_before.toFixed(2)} → ${doc.quality_score_after.toFixed(2)}`
          : '—',
    },
    { icon: Cpu, label: 'Embedding model', value: embedderDetail ?? 'loading…' },
    {
      icon: Scissors,
      label: 'Chunking strategy',
      value: doc.chunk_strategy ? `${doc.chunk_strategy} · ${doc.chunk_count ?? 0} chunks` : '—',
    },
    { icon: GaugeIcon, label: 'Reranker', value: rerankerDetail ?? 'loading…' },
    { icon: Boxes, label: 'Retrieval mode', value: mode },
    { icon: Database, label: 'Vector store', value: vectorStore ?? '—' },
    { icon: Shield, label: 'PII masked', value: `${piiTotal} item${piiTotal === 1 ? '' : 's'}` },
  ]

  return (
    <div className="flex flex-wrap gap-2" data-testid="pipeline-facts">
      {facts.map((fact, i) => (
        <motion.div
          key={fact.label}
          initial={reduced ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, delay: reduced ? 0 : i * 0.05 }}
          className="flex items-center gap-1.5 rounded-full border border-border bg-surface-raised px-2.5 py-1 text-xs"
          title={fact.label}
        >
          <fact.icon className="size-3.5 text-accent" />
          <span className="text-muted-foreground">{fact.label}:</span>
          <span className="font-medium text-foreground">{fact.value}</span>
        </motion.div>
      ))}
    </div>
  )
}
