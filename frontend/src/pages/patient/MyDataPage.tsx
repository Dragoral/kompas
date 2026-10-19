import { useState } from 'react'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

function download(data: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function MyDataPage() {
  const [withdrawn, setWithdrawn] = useState(false)
  const exportData = useAction(() => api.get<unknown>('/api/me/export'))
  const withdraw = useAction(() => api.post('/api/me/consent/withdraw'))

  const onExport = async () => {
    const data = await exportData.run()
    if (data) download(data, `kompas-${new Date().toISOString().slice(0, 10)}.json`)
  }

  const onWithdraw = async () => {
    if (!window.confirm('Отозвать согласие? Дистанционное наблюдение прекратится, данные будут удалены по истечении срока хранения.')) return
    if (await withdraw.run()) setWithdrawn(true)
  }

  return (
    <>
      <h1>Мои данные</h1>
      <section aria-labelledby="export-h">
        <h2 id="export-h">Получить копию данных</h2>
        <p>Файл со всеми вашими данными: дневник, опросники, сообщения, нежелательные реакции.</p>
        <ErrorMessage error={exportData.error} />
        <button type="button" className="secondary" disabled={exportData.pending} onClick={onExport}>Скачать (JSON)</button>
      </section>
      <section aria-labelledby="consent-h">
        <h2 id="consent-h">Согласие на обработку персональных данных</h2>
        {withdrawn ? (
          <p className="message" role="status">Согласие отозвано.</p>
        ) : (
          <>
            <p>Вы можете отозвать согласие в любой момент (152-ФЗ, ст. 9).</p>
            <ErrorMessage error={withdraw.error} />
            <button type="button" className="secondary danger" disabled={withdraw.pending} onClick={onWithdraw}>Отозвать согласие</button>
          </>
        )}
      </section>
    </>
  )
}
