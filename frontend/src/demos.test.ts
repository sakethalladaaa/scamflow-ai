import { expect, it } from 'vitest'
import { demos, revealedPrefix } from './demos'

it('only returns the revealed prefix and no evaluation labels', () => {
  const scenario = demos[0]
  const first = revealedPrefix(scenario, 1)
  expect(first).toHaveLength(1)
  expect(first[0].text).toBe(scenario.events[0].text)
  expect(JSON.stringify(first)).not.toContain(scenario.events[1].text)
  expect(JSON.stringify(first).toLowerCase()).not.toContain('expected')
})
