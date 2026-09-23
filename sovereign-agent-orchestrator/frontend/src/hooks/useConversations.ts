import useSWR from 'swr'
import { getConversation, listConversations } from '../services/api'
import { useAuth } from '../context/AuthContext'

export function useConversations() {
  const { token } = useAuth()
  const { data, error, isLoading, mutate } = useSWR(
    token ? ['conversations', token] : null,
    ([, authToken]) => listConversations(authToken),
    { refreshInterval: 15000 },
  )
  return { conversations: data?.data ?? [], error, isLoading, mutate }
}

export function useConversation(conversationId?: string) {
  const { token } = useAuth()
  const { data, error, isLoading, mutate } = useSWR(
    token && conversationId ? ['conversation', conversationId, token] : null,
    ([, id, authToken]) => getConversation(id, authToken),
    { refreshInterval: 4000 },
  )
  // The server orders messages by UUID id, which isn't chronological -- sort by timestamp.
  const messages = [...(data?.messages ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at))
  return { conversation: data?.data, messages, error, isLoading, mutate }
}
