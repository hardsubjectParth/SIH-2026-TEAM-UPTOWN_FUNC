import { motion } from 'framer-motion'

function MetricRow({ label, value, index = 0 }: { label: string; value: string; index?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: index * 0.04, duration: 0.25 }}
      className="flex items-center justify-between border-b border-rule py-2 text-sm last:border-b-0"
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="stat-number text-foreground">{value}</span>
    </motion.div>
  )
}

export default MetricRow
