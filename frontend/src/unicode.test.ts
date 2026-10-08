import { describe, expect, it } from 'vitest'
import { codePointToUtf16Offset, splitEvidence } from './unicode'

describe('Python code-point evidence offsets', () => {
  it('converts offsets after emoji and preserves combining characters', () => {
    const text = '🙂 cafe\u0301 refund refund'
    const points = Array.from(text)
    const start = points.join('').indexOf('refund') // UTF-16 index is intentionally wrong here
    const codePointStart = points.slice(0, 8).length
    expect(codePointToUtf16Offset(text, codePointStart)).toBe(9)
    expect(splitEvidence(text, codePointStart, codePointStart + 6)).toEqual(['🙂 café ', 'refund', ' refund'])
    expect(start).toBe(9)
  })

  it('selects a repeated quote by its exact span, not by text search', () => {
    expect(splitEvidence('refund then refund', 12, 18)).toEqual(['refund then ', 'refund', ''])
  })
})
