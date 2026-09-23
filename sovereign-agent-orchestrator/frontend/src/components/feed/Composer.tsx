import { useRef, useState } from 'react'
import type { FormEvent } from 'react'

export const SUPPORTED_UPLOAD_TYPES = '.pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.txt,.md,.png,.jpg,.jpeg,.tiff,.bmp'

type ComposerProps = {
  onSubmit: (task: string, files: File[]) => Promise<boolean>
  submitting: boolean
}

function Composer({ onSubmit, submitting }: ComposerProps) {
  const [task, setTask] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [focused, setFocused] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function grow() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!task.trim() || submitting) return
    // Keep the draft when submission fails so the user doesn't lose their message.
    const sent = await onSubmit(task.trim(), files)
    if (!sent) return
    setTask('')
    setFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
    requestAnimationFrame(grow)
  }

  return (
    <div className="border-t border-white/8 px-4 py-4 sm:px-6">
      <form
        onSubmit={handleSubmit}
        className={`work-panel !rounded-[28px] flex items-end gap-2 px-3 py-2 transition-colors ${focused ? 'border-accent shadow-[0_0_0_1px_var(--color-accent)]' : ''}`}
      >
        <label htmlFor="composer-task" className="sr-only">Task instructions</label>
        <textarea
          id="composer-task"
          ref={textareaRef}
          rows={1}
          value={task}
          onChange={(event) => { setTask(event.target.value); grow() }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
          placeholder="Instruct Sovereign Intelligence..."
          className="chat-typing max-h-40 flex-1 resize-none bg-transparent py-1.5 text-base text-foreground outline-none placeholder:text-muted-foreground"
        />

        <label className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center text-muted-foreground focus-within:text-foreground focus-within:outline-2 focus-within:outline-accent hover:text-foreground" title="Attach files">
          <span aria-hidden="true">+</span>
          <span className="sr-only">Attach files</span>
          <input ref={fileInputRef} type="file" multiple accept={SUPPORTED_UPLOAD_TYPES} className="sr-only" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
        </label>

        <button
          type="submit"
          disabled={submitting || !task.trim()}
          aria-label={submitting ? 'Sending' : 'Send task'}
          className="action-primary h-8 w-8 shrink-0 text-base"
        >
          <span aria-hidden="true">{submitting ? '…' : '↑'}</span>
        </button>
      </form>

      {files.length > 0 ? (
        <ul aria-label="Attached files" className="mt-2 flex flex-wrap gap-1.5">
          {files.map((file) => <li key={`${file.name}-${file.size}-${file.lastModified}`} className="border-hairline rounded-full bg-white/5 px-3 py-1 text-xs text-muted-foreground">{file.name}</li>)}
        </ul>
      ) : null}
    </div>
  )
}

export default Composer
