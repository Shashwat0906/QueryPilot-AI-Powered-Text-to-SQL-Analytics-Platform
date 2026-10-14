import { Link } from 'react-router-dom'
import { EmptyState } from '../components/States'

export function NotFoundPage() {
  return (
    <EmptyState title="This page doesn’t exist">
      <Link to="/" className="text-amber hover:underline">
        Go to the Ask page
      </Link>
    </EmptyState>
  )
}
