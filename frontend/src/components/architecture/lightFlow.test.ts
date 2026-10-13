import { describe, expect, it } from 'vitest'
import { EDGE_LAYOUT_BY_ID } from './architectureLayout'
import { LIGHT_FLOW_STAGES } from './lightFlowStages'
import { PIPELINE_STAGE_TO_EDGE } from './traceStageMapping'

/** Pure frontend-internal consistency — no backend required, unlike
 * architectureLayout.contract.test.ts. Every edge id referenced by a light-flow stage or a
 * pipeline-stage mapping must actually exist in EDGE_LAYOUT, or Tour/Live mode would try to
 * animate a comet along a path that was never drawn. */
describe('light flow edge references are all real EDGE_LAYOUT ids', () => {
  it('every LIGHT_FLOW_STAGES edgeId exists in EDGE_LAYOUT', () => {
    const unknown = LIGHT_FLOW_STAGES.flatMap((stage) =>
      stage.edgeIds.filter((id) => !(id in EDGE_LAYOUT_BY_ID)).map((id) => `${stage.name}:${id}`),
    )
    expect(unknown).toEqual([])
  })

  it('every PIPELINE_STAGE_TO_EDGE value exists in EDGE_LAYOUT', () => {
    const unknown = Object.entries(PIPELINE_STAGE_TO_EDGE)
      .filter(([, edgeId]) => !(edgeId in EDGE_LAYOUT_BY_ID))
      .map(([stage, edgeId]) => `${stage} -> ${edgeId}`)
    expect(unknown).toEqual([])
  })

  it('LIGHT_FLOW_STAGES covers all 5 stages exactly once, in order', () => {
    expect(LIGHT_FLOW_STAGES.map((s) => s.id)).toEqual([1, 2, 3, 4, 5])
  })
})
