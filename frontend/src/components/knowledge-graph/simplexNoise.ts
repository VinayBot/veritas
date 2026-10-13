/**
 * Minimal, self-contained, seedable 3D simplex noise (classic Perlin-improved simplex, after
 * Stefan Gustavson's public-domain reference implementation). Hand-rolled rather than adding
 * a noise library — G5 restricts new runtime dependencies to three/@types/three only, and the
 * surface this needs (one deterministic `noise3D(x,y,z) -> [-1,1]`) is small enough that a
 * ~90-line implementation is simpler than vetting and pulling in a whole package for it.
 */

const F3 = 1 / 3
const G3 = 1 / 6

const GRAD3 = [
  [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
  [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
  [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
]

/** Deterministic PRNG (mulberry32) so a given seed always produces the same permutation —
 * the brief requires the torus's lumpy shape to be stable across reloads. */
function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export class SimplexNoise {
  private perm = new Uint8Array(512)

  constructor(seed: number) {
    const rand = mulberry32(seed)
    const p = new Uint8Array(256)
    for (let i = 0; i < 256; i++) p[i] = i
    for (let i = 255; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1))
      ;[p[i], p[j]] = [p[j], p[i]]
    }
    for (let i = 0; i < 512; i++) this.perm[i] = p[i & 255]
  }

  noise3D(xin: number, yin: number, zin: number): number {
    const perm = this.perm
    const s = (xin + yin + zin) * F3
    const i = Math.floor(xin + s)
    const j = Math.floor(yin + s)
    const k = Math.floor(zin + s)
    const t = (i + j + k) * G3
    const x0 = xin - (i - t)
    const y0 = yin - (j - t)
    const z0 = zin - (k - t)

    let i1 = 0, j1 = 0, k1 = 0
    let i2 = 0, j2 = 0, k2 = 0
    if (x0 >= y0) {
      if (y0 >= z0) { i1 = 1; i2 = 1; j2 = 1 }
      else if (x0 >= z0) { i1 = 1; i2 = 1; k2 = 1 }
      else { k1 = 1; i2 = 1; k2 = 1 }
    } else {
      if (y0 < z0) { k1 = 1; j2 = 1; k2 = 1 }
      else if (x0 < z0) { j1 = 1; j2 = 1; k2 = 1 }
      else { j1 = 1; i2 = 1; j2 = 1 }
    }

    const x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3
    const x2 = x0 - i2 + 2 * G3, y2 = y0 - j2 + 2 * G3, z2 = z0 - k2 + 2 * G3
    const x3 = x0 - 1 + 3 * G3, y3 = y0 - 1 + 3 * G3, z3 = z0 - 1 + 3 * G3

    const ii = i & 255, jj = j & 255, kk = k & 255

    const contribution = (gi: number, x: number, y: number, z: number): number => {
      let t2 = 0.6 - x * x - y * y - z * z
      if (t2 < 0) return 0
      const g = GRAD3[gi % 12]
      t2 *= t2
      return t2 * t2 * (g[0] * x + g[1] * y + g[2] * z)
    }

    const gi0 = perm[ii + perm[jj + perm[kk]]]
    const gi1 = perm[ii + i1 + perm[jj + j1 + perm[kk + k1]]]
    const gi2 = perm[ii + i2 + perm[jj + j2 + perm[kk + k2]]]
    const gi3 = perm[ii + 1 + perm[jj + 1 + perm[kk + 1]]]

    const n0 = contribution(gi0, x0, y0, z0)
    const n1 = contribution(gi1, x1, y1, z1)
    const n2 = contribution(gi2, x2, y2, z2)
    const n3 = contribution(gi3, x3, y3, z3)

    return 32 * (n0 + n1 + n2 + n3)
  }
}
