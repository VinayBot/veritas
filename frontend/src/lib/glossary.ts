/** Plain-English explanations for every metric and term the UI shows. One place, so a
 * tooltip on the Dashboard and the same term on Evaluation never disagree. */
export const GLOSSARY = {
  faithfulness:
    'How much of the answer is backed by the retrieved text. 1.00 means every claim is supported; low values mean the model added things the documents do not say. Scored by a judge model.',
  grounding:
    'The share of sentences in this answer that a checker model found support for in the retrieved text.',
  relevancy:
    'How directly the answer addresses the question that was asked, regardless of whether it is correct. Scored by a judge model.',
  correctness:
    'How closely the answer matches a known reference answer. Only available in evaluation runs, where a reference exists.',
  citation_validity:
    'The share of citation markers like [2] that point at a source that was actually retrieved. Catches invented citations.',
  confidence: 'The average of the quality scores that could be measured for this answer.',
  precision:
    'Of the top 5 chunks retrieved, the share that were actually relevant to the question. Higher means less noise.',
  recall:
    'Of all the chunks that should have been found for the question, the share that appeared in the top 5. Higher means less was missed.',
  ndcg:
    'Ranking quality of the top 5 results: relevant chunks near the top score higher than the same chunks further down. 1.00 is a perfect ordering.',
  mrr: 'How high the first relevant chunk ranks, on average. 1.00 means it is always first.',
  hit_rate: 'How often at least one relevant chunk appears in the top 5.',
  p50: 'Median latency: half of requests were faster than this.',
  p95: 'Tail latency: 95% of requests were faster than this. Shows the slow cases.',
  rrf: 'Reciprocal Rank Fusion: a way of merging a keyword ranking and a meaning-based ranking into one list by rewarding chunks that rank well in either.',
  rerank:
    'A second, slower model re-reads each candidate chunk together with the question and re-orders them by how well they actually answer it.',
  hyde: 'Hypothetical Document Embeddings: the model first writes a guess at the answer, and that guess is used to search. Helps short or vague questions.',
  mmr: 'Maximal Marginal Relevance: drops near-duplicate chunks so the context covers more ground.',
  bm25: 'Classic keyword search. Matches exact words and rare terms well; misses paraphrases.',
  dense: 'Search by meaning using embeddings. Finds paraphrases; can miss exact identifiers.',
  chunk: 'A passage of the document, cut to a size the model can read. Retrieval works on chunks, not whole documents.',
  embedding: 'A list of numbers representing the meaning of a piece of text, used for search by meaning.',
  production_score:
    'A weighted blend of faithfulness, correctness, ranking quality and safety, minus a latency penalty. Used to pick a recommended configuration.',
  hard_gates:
    'Minimum bars a configuration must clear to be recommended: faithfulness at least 0.85, injection block rate at least 95%, zero PII leaks, p95 latency at most 15 seconds.',
  block_rate: 'The share of known attack prompts that the guardrails stopped.',
  false_positive_rate: 'The share of harmless prompts that the guardrails wrongly blocked.',
  estimated:
    'Estimated: scored without a reference answer, so it reflects the judge model’s opinion only.',
  verified: 'Verified: scored against a known reference answer from an evaluation set.',
  not_measured: 'This value was not computed for this run. Nothing is shown rather than a guess.',
  entity_density: 'Distinct named things (people, organisations, places, dates) per 1,000 tokens.',
  cross_references:
    'How often the document points at other parts of itself ("see section 4"). Many of these suggest questions that need facts from several places.',
  lexical_diversity: 'Share of distinct words. Low values mean repetitive text.',
  tokens: 'Pieces of words the model reads and writes. Roughly 4 characters or 0.75 words each.',
  orphan_rate: 'The share of entities in the graph with no relation to any other entity.',
  community: 'A cluster of entities that are more connected to each other than to the rest of the graph.',
  zero_citation: 'Answers that cited no source at all. A warning sign: the answer may not come from the documents.',
  retry_rate: 'How often the agent had to search again or rewrite its answer before it was satisfied.',
  agreement:
    'How closely the council’s models agreed when scoring each other’s answers. 1.00 is full agreement.',
} as const

export type GlossaryTerm = keyof typeof GLOSSARY
