import useSWR from 'swr'
import { deleteFile, getUploadScopes, listFiles, uploadFile } from '../services/api'
import { useAuth } from '../context/AuthContext'

export function useFiles() {
  const { token } = useAuth()
  const { data, error, isLoading, mutate } = useSWR(
    token ? ['files', token] : null,
    ([, authToken]) => listFiles(authToken),
    { refreshInterval: 10000 },
  )
  return { files: data?.data ?? [], error, isLoading, mutate }
}

export function useFileScopes() {
  const { token } = useAuth()
  const { data, error, isLoading } = useSWR(token ? ['upload-scopes', token] : null, ([, authToken]) => getUploadScopes(authToken))
  return { scopes: data?.scopes ?? [], error, isLoading }
}

export function useUploadFile() {
  const { token } = useAuth()
  return (file: File, scope: string) => {
    if (!token) return Promise.reject(new Error('Not authenticated'))
    return uploadFile(file, scope, token)
  }
}

export function useDeleteFile() {
  const { token } = useAuth()
  return (fileId: string) => {
    if (!token) return Promise.reject(new Error('Not authenticated'))
    return deleteFile(fileId, token)
  }
}
