import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost'

const STYLES: Record<Variant, string> = {
  primary: 'bg-amber text-night hover:bg-[#f5c465] font-semibold',
  secondary: 'border border-line-strong bg-raised text-ink hover:border-faint',
  ghost: 'text-muted hover:bg-raised hover:text-ink',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  icon?: ReactNode
  size?: 'sm' | 'md'
}

export function Button({ variant = 'secondary', icon, size = 'md', className = '', children, ...rest }: ButtonProps) {
  const sizing = size === 'sm' ? 'h-8 px-2.5 text-sm gap-1.5' : 'h-10 px-4 text-sm gap-2'
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${STYLES[variant]} ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </button>
  )
}
