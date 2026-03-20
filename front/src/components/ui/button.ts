import { cva, type VariantProps } from 'class-variance-authority'

export const buttonVariants = cva(
    'inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98]',
    {
        variants: {
            variant: {
                default: 'bg-zinc-900 text-zinc-50 hover:bg-zinc-800 focus-visible:ring-zinc-500',
                ghost: 'bg-transparent text-zinc-700 hover:bg-zinc-100 focus-visible:ring-zinc-400',
                secondary: 'bg-zinc-100 text-zinc-900 hover:bg-zinc-200 focus-visible:ring-zinc-400',
            },
            size: {
                default: 'h-10 px-4 py-2',
                sm: 'h-8 rounded-lg px-3',
                lg: 'h-11 rounded-xl px-6',
                icon: 'h-10 w-10',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    },
)

export type ButtonVariants = VariantProps<typeof buttonVariants>
