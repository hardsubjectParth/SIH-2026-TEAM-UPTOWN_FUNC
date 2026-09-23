import type { Role } from '../../types/api'

// Keep the backend's role keys unchanged until identity and authorization are migrated together.
export const RANK: Record<Role, { name: string; subtitle: string; description: string; knowledgeAccess: string }> = {
  admin: {
    name: 'Workspace Administrator',
    subtitle: 'Administrative access',
    description: 'Oversee workspace operations and access all authorized knowledge classifications.',
    knowledgeAccess: 'Confidential, Restricted and Shared',
  },
  higher: {
    name: 'Operations Reviewer',
    subtitle: 'Review access',
    description: 'Review accessible operations and work with restricted and shared knowledge.',
    knowledgeAccess: 'Restricted and Shared',
  },
  lower: {
    name: 'Operations Analyst',
    subtitle: 'Standard access',
    description: 'Run tasks and work with shared knowledge in your workspace.',
    knowledgeAccess: 'Shared',
  },
}

export const KNOWLEDGE_CLASSIFICATION: Record<Role, string> = {
  admin: 'Confidential',
  higher: 'Restricted',
  lower: 'Shared',
}
