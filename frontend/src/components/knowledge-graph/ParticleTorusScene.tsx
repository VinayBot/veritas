import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { GraphEdge } from '@/lib/api/types'
import { buildFieldPoints, type EntityPoint } from './knowledgeGraphLayout'

const FIELD_VERTEX_SHADER = `
  attribute float size;
  void main() {
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * (700.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
  }
`
const FIELD_FRAGMENT_SHADER = `
  void main() {
    float d = length(gl_PointCoord - vec2(0.5));
    if (d > 0.5) discard;
    float alpha = (1.0 - d * 2.0) * 0.28;
    gl_FragColor = vec4(0.81, 0.83, 1.0, alpha);
  }
`

const ENTITY_VERTEX_SHADER = `
  attribute float size;
  attribute vec3 color;
  attribute float opacity;
  varying vec3 vColor;
  varying float vOpacity;
  void main() {
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * (700.0 / -mvPosition.z);
    gl_Position = projectionMatrix * mvPosition;
    vColor = color;
    vOpacity = opacity;
  }
`
const ENTITY_FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vOpacity;
  void main() {
    float d = length(gl_PointCoord - vec2(0.5));
    if (d > 0.5) discard;
    float alpha = (1.0 - d * 2.0) * vOpacity;
    gl_FragColor = vec4(vColor, alpha);
  }
`

export interface ParticleTorusSceneProps {
  entities: EntityPoint[]
  edges: GraphEdge[]
  fieldCount: number
  reducedMotion: boolean
  onHoverEntity: (entity: EntityPoint | null, screenPos: { x: number; y: number } | null) => void
  onClickEntity: (entity: EntityPoint | null) => void
  onLowFps?: () => void
  highlightSequence?: string[]
  onHighlightStep?: (entityId: string) => void
}

const MAX_FOCUS_EDGES = 200
const LOW_FPS_THRESHOLD = 45
const LOW_FPS_SUSTAINED_MS = 2000

interface SceneState {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  group: THREE.Group
  entityPoints: THREE.Points
  fieldPoints: THREE.Points
  focusLines: THREE.LineSegments
  entityGeometry: THREE.BufferGeometry
  raycaster: THREE.Raycaster
  rotation: { azimuth: number; elevation: number }
  autoRotate: number
  visible: boolean
  frameTimes: number[]
  lowFpsSince: number | null
  lowFpsReported: boolean
  disposed: boolean
}

/** KG-1: real knowledge graph rendered as a lumpy, off-centre-holed particle torus via
 * three.js Points + a custom ShaderMaterial (additive blending, depthWrite:false,
 * distance-attenuated point size, DPR capped at 2). All interaction state (hover/focus/
 * highlight) mutates BufferAttributes imperatively from event handlers or short timeout
 * chains — never per-frame React state (G9). */
export function ParticleTorusScene({
  entities,
  edges,
  fieldCount,
  reducedMotion,
  onHoverEntity,
  onClickEntity,
  onLowFps,
  highlightSequence,
  onHighlightStep,
}: ParticleTorusSceneProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const stateRef = useRef<SceneState | null>(null)

  // Always-fresh refs so the mount-only effect's event handlers never close over a stale
  // prop/callback from the render they were created in.
  const entitiesRef = useRef(entities)
  entitiesRef.current = entities
  const edgesRef = useRef(edges)
  edgesRef.current = edges
  const onHoverRef = useRef(onHoverEntity)
  onHoverRef.current = onHoverEntity
  const onLowFpsRef = useRef(onLowFps)
  onLowFpsRef.current = onLowFps

  function applyFocus(entityId: string | null) {
    const s = stateRef.current
    if (!s) return
    const currentEntities = entitiesRef.current
    const opacityAttr = s.entityGeometry.getAttribute('opacity') as THREE.BufferAttribute | undefined
    if (!opacityAttr || opacityAttr.count !== currentEntities.length) return
    if (!entityId) {
      for (let i = 0; i < currentEntities.length; i++) opacityAttr.setX(i, 1)
      opacityAttr.needsUpdate = true
      s.focusLines.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
      return
    }
    const byId = new Map(currentEntities.map((e) => [e.id, e]))
    const focused = byId.get(entityId)
    const neighborIds = new Set<string>()
    const linePositions: number[] = []
    let lineCount = 0
    for (const edge of edgesRef.current) {
      if (lineCount >= MAX_FOCUS_EDGES) break
      if (edge.source === entityId) neighborIds.add(edge.target)
      else if (edge.target === entityId) neighborIds.add(edge.source)
      else continue
      const other = byId.get(edge.source === entityId ? edge.target : edge.source)
      if (focused && other) {
        linePositions.push(...focused.position, ...other.position)
        lineCount++
      }
    }
    currentEntities.forEach((e, i) => {
      const dim = e.id !== entityId && !neighborIds.has(e.id)
      opacityAttr.setX(i, dim ? 0.15 : 1)
    })
    opacityAttr.needsUpdate = true
    s.focusLines.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(linePositions), 3))
  }
  const applyFocusRef = useRef(applyFocus)
  applyFocusRef.current = applyFocus

  const onClickRef = useRef((entity: EntityPoint | null) => {
    applyFocusRef.current(entity?.id ?? null)
    onClickEntity(entity)
  })
  onClickRef.current = (entity: EntityPoint | null) => {
    applyFocusRef.current(entity?.id ?? null)
    onClickEntity(entity)
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
    camera.position.set(0, 0, 3.2)

    // KG-1/KG-4: pure black canvas, always — not the app's current light/dark theme
    // background (the brief's reference image is explicitly black regardless of theme).
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setClearColor(0x000000, 1)
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
    container.appendChild(renderer.domElement)

    const group = new THREE.Group()
    group.rotation.x = 0.5
    group.rotation.z = 0.15
    scene.add(group)

    const fieldGeometry = new THREE.BufferGeometry()
    const fieldMaterial = new THREE.ShaderMaterial({
      vertexShader: FIELD_VERTEX_SHADER,
      fragmentShader: FIELD_FRAGMENT_SHADER,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const fieldPoints = new THREE.Points(fieldGeometry, fieldMaterial)
    group.add(fieldPoints)

    const entityGeometry = new THREE.BufferGeometry()
    const entityMaterial = new THREE.ShaderMaterial({
      vertexShader: ENTITY_VERTEX_SHADER,
      fragmentShader: ENTITY_FRAGMENT_SHADER,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const entityPoints = new THREE.Points(entityGeometry, entityMaterial)
    group.add(entityPoints)

    const focusLineMaterial = new THREE.LineBasicMaterial({
      color: 0xcfd3ff,
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending,
    })
    const focusLines = new THREE.LineSegments(new THREE.BufferGeometry(), focusLineMaterial)
    group.add(focusLines)

    const raycaster = new THREE.Raycaster()
    raycaster.params.Points = { threshold: 0.06 }

    const state: SceneState = {
      renderer,
      scene,
      camera,
      group,
      entityPoints,
      fieldPoints,
      focusLines,
      entityGeometry,
      raycaster,
      rotation: { azimuth: 0, elevation: 0 },
      autoRotate: 0,
      visible: true,
      frameTimes: [],
      lowFpsSince: null,
      lowFpsReported: false,
      disposed: false,
    }
    stateRef.current = state

    const resize = () => {
      const w = container.clientWidth
      const h = container.clientHeight
      if (w === 0 || h === 0) return
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(container)

    const onVisibility = () => {
      state.visible = !document.hidden
    }
    document.addEventListener('visibilitychange', onVisibility)
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      state.visible = entry.isIntersecting && !document.hidden
    })
    intersectionObserver.observe(container)

    let rafId = 0
    let lastFrameAt = performance.now()
    const animate = () => {
      if (state.disposed) return
      rafId = requestAnimationFrame(animate)
      if (!state.visible) {
        lastFrameAt = performance.now()
        return
      }

      const now = performance.now()
      const frameDuration = now - lastFrameAt
      lastFrameAt = now
      state.frameTimes.push(frameDuration)
      if (state.frameTimes.length > 120) state.frameTimes.shift()

      // G9: adaptive quality — halve field density if sustained below 45fps for 2s.
      const avgFrameMs = state.frameTimes.reduce((a, b) => a + b, 0) / state.frameTimes.length
      const fps = avgFrameMs > 0 ? 1000 / avgFrameMs : 60
      if (fps < LOW_FPS_THRESHOLD) {
        if (state.lowFpsSince === null) state.lowFpsSince = now
        else if (!state.lowFpsReported && now - state.lowFpsSince > LOW_FPS_SUSTAINED_MS) {
          state.lowFpsReported = true
          onLowFpsRef.current?.()
        }
      } else {
        state.lowFpsSince = null
      }

      if (!reducedMotion) {
        state.autoRotate += 0.0008
        state.group.rotation.y = state.rotation.azimuth + state.autoRotate
        state.group.position.y = Math.sin(now * 0.0003) * 0.03
      } else {
        state.group.rotation.y = state.rotation.azimuth
      }
      state.group.rotation.x = 0.5 + state.rotation.elevation

      renderer.render(scene, camera)
    }
    rafId = requestAnimationFrame(animate)

    // Drag to rotate; wheel only zooms with ctrl/meta (pinch-zoom sends wheel+ctrlKey too) —
    // plain wheel is left alone so the page scrolls (SC-3's rule, reused here).
    // `dragging` tracks "button is down"; `moved` tracks whether the pointer actually
    // travelled past a small threshold while down — ONLY `moved` should suppress the click
    // handler on pointerup. Using `dragging` itself there was a real bug: it's set true on
    // every pointerdown unconditionally, so a plain click-with-zero-movement always read as
    // "was dragging" and the click-to-focus handler never ran at all (confirmed live: a
    // raycast fed the exact NDC of a known entity hit correctly, but no real click, however
    // precisely aimed, ever did — this was why).
    const DRAG_THRESHOLD_PX = 4
    let dragging = false
    let moved = false
    let lastX = 0
    let lastY = 0
    const onPointerDown = (e: PointerEvent) => {
      dragging = true
      moved = false
      lastX = e.clientX
      lastY = e.clientY
    }
    const onPointerMove = (e: PointerEvent) => {
      if (dragging) {
        const dx = e.clientX - lastX
        const dy = e.clientY - lastY
        if (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX) moved = true
        lastX = e.clientX
        lastY = e.clientY
        state.rotation.azimuth += dx * 0.005
        state.rotation.elevation = Math.max(-0.6, Math.min(0.6, state.rotation.elevation + dy * 0.005))
        return
      }
      const rect = container.getBoundingClientRect()
      const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1
      const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera)
      const hits = raycaster.intersectObject(entityPoints)
      if (hits.length > 0 && hits[0].index !== undefined) {
        onHoverRef.current(entitiesRef.current[hits[0].index] ?? null, { x: e.clientX, y: e.clientY })
      } else {
        onHoverRef.current(null, null)
      }
    }
    const onPointerUp = (e: PointerEvent) => {
      const wasDragging = dragging && moved
      dragging = false
      if (wasDragging) return
      const rect = container.getBoundingClientRect()
      const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1
      const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera)
      const hits = raycaster.intersectObject(entityPoints)
      if (hits.length > 0 && hits[0].index !== undefined) {
        onClickRef.current(entitiesRef.current[hits[0].index] ?? null)
      } else {
        onClickRef.current(null)
      }
    }
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const delta = e.deltaY > 0 ? 1.08 : 0.93
      camera.position.z = Math.min(8, Math.max(1.4, camera.position.z * delta))
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClickRef.current(null)
    }

    container.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    container.addEventListener('wheel', onWheel, { passive: false })
    window.addEventListener('keydown', onKeyDown)

    return () => {
      state.disposed = true
      cancelAnimationFrame(rafId)
      resizeObserver.disconnect()
      intersectionObserver.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      container.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      container.removeEventListener('wheel', onWheel)
      window.removeEventListener('keydown', onKeyDown)
      fieldGeometry.dispose()
      fieldMaterial.dispose()
      entityGeometry.dispose()
      entityMaterial.dispose()
      focusLineMaterial.dispose()
      renderer.dispose()
      container.removeChild(renderer.domElement)
      stateRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Rebuild field geometry when fieldCount changes (initial mount, or adaptive-quality halving).
  useEffect(() => {
    const s = stateRef.current
    if (!s) return
    const field = buildFieldPoints(fieldCount)
    const positions = new Float32Array(field.length * 3)
    const sizes = new Float32Array(field.length)
    field.forEach((p, i) => {
      positions[i * 3] = p.position[0]
      positions[i * 3 + 1] = p.position[1]
      positions[i * 3 + 2] = p.position[2]
      sizes[i] = 0.01
    })
    s.fieldPoints.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    s.fieldPoints.geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
  }, [fieldCount])

  // Rebuild entity geometry when the real entity list changes (document switch, data load).
  useEffect(() => {
    const s = stateRef.current
    if (!s) return
    const positions = new Float32Array(entities.length * 3)
    const colors = new Float32Array(entities.length * 3)
    const sizes = new Float32Array(entities.length)
    const opacities = new Float32Array(entities.length).fill(1)
    entities.forEach((e, i) => {
      positions[i * 3] = e.position[0]
      positions[i * 3 + 1] = e.position[1]
      positions[i * 3 + 2] = e.position[2]
      colors[i * 3] = e.color[0]
      colors[i * 3 + 1] = e.color[1]
      colors[i * 3 + 2] = e.color[2]
      sizes[i] = Math.max(0.018, e.size)
    })
    s.entityGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    s.entityGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    s.entityGeometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
    s.entityGeometry.setAttribute('opacity', new THREE.BufferAttribute(opacities, 1))
  }, [entities])

  // KG-5: step through a real traversal/linked-entity sequence by pulsing each entity's size
  // in order — a short setTimeout chain (user-triggered, not a continuous animation loop),
  // skipped entirely under reduced motion.
  useEffect(() => {
    if (!highlightSequence || highlightSequence.length === 0 || reducedMotion) return
    let cancelled = false
    let i = 0
    const step = () => {
      if (cancelled || i >= highlightSequence.length) return
      const s = stateRef.current
      const sizeAttr = s?.entityGeometry.getAttribute('size') as THREE.BufferAttribute | undefined
      const idx = entitiesRef.current.findIndex((e) => e.id === highlightSequence[i])
      if (sizeAttr && idx >= 0) {
        const base = Math.max(0.018, entitiesRef.current[idx].size)
        sizeAttr.setX(idx, base * 2.2)
        sizeAttr.needsUpdate = true
        onHighlightStep?.(highlightSequence[i])
        window.setTimeout(() => {
          if (cancelled) return
          sizeAttr.setX(idx, base)
          sizeAttr.needsUpdate = true
        }, 500)
      }
      i++
      window.setTimeout(step, 650)
    }
    step()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightSequence])

  return (
    <div
      ref={containerRef}
      className="h-full w-full bg-black"
      data-testid="knowledge-graph-canvas-container"
    />
  )
}
