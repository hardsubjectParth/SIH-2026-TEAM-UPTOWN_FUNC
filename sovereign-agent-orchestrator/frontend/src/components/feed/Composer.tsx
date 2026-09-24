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
    // The rule spans the window, but the input itself is capped at max-w-2xl to match
    // the message column in IntelligenceFeedPage -- so it lines up with the turns it
    // produces rather than running the full width of the workspace.
    <div className="border-t border-rule px-4 py-4 sm:px-6">
      <form
        onSubmit={handleSubmit}
        className={`work-panel !rounded-[28px] mx-auto flex w-full max-w-2xl items-end gap-2 px-3 py-2 transition-colors ${focused ? 'border-accent shadow-[0_0_0_1px_var(--color-accent)]' : ''}`}
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
          className="chat-typing composer-input max-h-40 flex-1 resize-none bg-transparent py-1.5 text-base text-foreground outline-none placeholder:text-muted-foreground"
        />

        <label className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors focus-within:text-foreground focus-within:outline-2 focus-within:outline-accent hover:bg-fill hover:text-foreground" title="Attach files">
          <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
          <span className="sr-only">Attach files</span>
          <input ref={fileInputRef} type="file" multiple accept={SUPPORTED_UPLOAD_TYPES} className="sr-only" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
        </label>

        <button
          type="submit"
          disabled={submitting || !task.trim()}
          aria-label={submitting ? 'Sending' : 'Send task'}
          className="action-primary size-9 shrink-0 text-lg"
        >
          <span aria-hidden="true">{submitting ? '…' : '↑'}</span>
        </button>
      </form>

      {files.length > 0 ? (
        <ul aria-label="Attached files" className="mx-auto mt-2 flex w-full max-w-2xl flex-wrap gap-1.5">
          {files.map((file) => <li key={`${file.name}-${file.size}-${file.lastModified}`} className="border-hairline rounded-full bg-fill px-3 py-1 text-xs text-muted-foreground">{file.name}</li>)}
        </ul>
      ) : null}
    </div>
  )
}

export default Composer
