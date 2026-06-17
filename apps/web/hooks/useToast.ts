import { create } from 'zustand'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: string
  type: ToastType
  message: string
  action?: { label: string; onClick: () => void }
  duration: number
}

interface ToastStore {
  toasts: ToastItem[]
  add: (type: ToastType, message: string, opts?: { action?: ToastItem['action']; duration?: number }) => void
  dismiss: (id: string) => void
}

const MAX_VISIBLE = 3

const DEFAULT_DURATION: Record<ToastType, number> = {
  success: 3000,
  error: 6000,
  warning: 5000,
  info: 4000,
}

let counter = 0

export const useToast = create<ToastStore>((set) => ({
  toasts: [],

  add: (type, message, opts) => {
    const id = `toast-${++counter}-${Date.now()}`
    const duration = opts?.duration ?? DEFAULT_DURATION[type]
    const item: ToastItem = { id, type, message, action: opts?.action, duration }

    set((s) => ({
      toasts: [...s.toasts.slice(-(MAX_VISIBLE - 1)), item],
    }))

    if (duration > 0) {
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
      }, duration)
    }
  },

  dismiss: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Shorthand helpers — usable outside React components */
export const toast = {
  success: (msg: string, opts?: { action?: ToastItem['action']; duration?: number }) =>
    useToast.getState().add('success', msg, opts),
  error: (msg: string, opts?: { action?: ToastItem['action']; duration?: number }) =>
    useToast.getState().add('error', msg, opts),
  warning: (msg: string, opts?: { action?: ToastItem['action']; duration?: number }) =>
    useToast.getState().add('warning', msg, opts),
  info: (msg: string, opts?: { action?: ToastItem['action']; duration?: number }) =>
    useToast.getState().add('info', msg, opts),
}
