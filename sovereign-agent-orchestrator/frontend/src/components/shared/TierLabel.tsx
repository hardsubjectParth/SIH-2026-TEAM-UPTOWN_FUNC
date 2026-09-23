import type { Tier } from '../../types/api'
import { KNOWLEDGE_CLASSIFICATION } from '../shell/rank'

function TierLabel({ tier }: { tier: Tier | string }) {
  const label = Object.hasOwn(KNOWLEDGE_CLASSIFICATION, tier)
    ? KNOWLEDGE_CLASSIFICATION[tier as Tier]
    : 'Unknown classification'
  return <span className="label-micro font-semibold text-foreground/70" title={`Knowledge classification: ${label}`}>{label}</span>
}

export default TierLabel
