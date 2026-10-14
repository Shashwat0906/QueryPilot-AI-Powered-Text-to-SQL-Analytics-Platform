import { MessageSquareText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState } from './States'

export function NoActiveQuery({ what }: { what: string }) {
  return (
    <EmptyState icon={<MessageSquareText size={28} />} title={`No ${what} to show yet`}>
      <p>
        Ask a question first, or reopen one from{' '}
        <Link to="/history" className="text-amber hover:underline">
          History
        </Link>
        .
      </p>
      <Link
        to="/"
        className="mt-4 inline-flex h-10 items-center rounded-lg bg-amber px-4 text-sm font-semibold text-night hover:bg-[#f5c465]"
      >
        Ask a question
      </Link>
    </EmptyState>
  )
}
