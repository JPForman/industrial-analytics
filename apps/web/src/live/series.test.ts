import { describe, expect, it } from 'vitest'
import { mergePoints } from './series'

describe('mergePoints', () => {
  it('dedupes by timestamp and sorts, whatever order backfill and live arrive in', () => {
    const live = [{ t: 3, v: 30 }]
    const backfill = [
      { t: 1, v: 10 },
      { t: 3, v: 30 },
      { t: 2, v: 20 },
    ]
    expect(mergePoints(live, backfill, 0)).toEqual([
      { t: 1, v: 10 },
      { t: 2, v: 20 },
      { t: 3, v: 30 },
    ])
    expect(mergePoints(backfill, live, 0)).toEqual(mergePoints(live, backfill, 0))
  })

  it('drops points older than the window', () => {
    expect(mergePoints([{ t: 1, v: 1 }], [{ t: 10, v: 2 }], 5)).toEqual([{ t: 10, v: 2 }])
  })
})
