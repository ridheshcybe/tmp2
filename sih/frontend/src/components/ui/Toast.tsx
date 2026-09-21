// ══════════════════════════════════════════════════════════════════════════════
// Toast Notification Component
// ══════════════════════════════════════════════════════════════════════════════

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

type ToastType = 'success' | 'warning' | 'error' | 'info';

interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (message: string, type?: ToastType, duration?: number) => void;
  removeToast: (id: string) => void;
}

// ══════════════════════════════════════════════════════════════════════════════
// Context
// ══════════════════════════════════════════════════════════════════════════════

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

// ══════════════════════════════════════════════════════════════════════════════
// Provider
// ══════════════════════════════════════════════════════════════════════════════

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, type: ToastType = 'info', duration = 3000) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type, duration }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </ToastContext.Provider>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Container
// ══════════════════════════════════════════════════════════════════════════════

function ToastContainer({ 
  toasts, 
  removeToast 
}: { 
  toasts: Toast[]; 
  removeToast: (id: string) => void;
}) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onClose={() => removeToast(toast.id)} />
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Toast Item
// ══════════════════════════════════════════════════════════════════════════════

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  useEffect(() => {
    if (toast.duration) {
      const timer = setTimeout(onClose, toast.duration);
      return () => clearTimeout(timer);
    }
  }, [toast.duration, onClose]);

  const icons = {
    success: <CheckCircle className="w-5 h-5 text-nominal-green" />,
    warning: <AlertTriangle className="w-5 h-5 text-hud-amber" />,
    error: <XCircle className="w-5 h-5 text-alert-red" />,
    info: <Info className="w-5 h-5 text-cyber-cyan" />,
  };

  const borderColors = {
    success: 'border-nominal-green',
    warning: 'border-hud-amber',
    error: 'border-alert-red',
    info: 'border-cyber-cyan',
  };

  return (
    <div className={clsx(
      'flex items-center gap-3 px-4 py-3 rounded-lg glass-card border animate-slide-in',
      borderColors[toast.type]
    )}>
      {icons[toast.type]}
      <span className="text-sm text-white">{toast.message}</span>
      <button onClick={onClose} className="ml-2 text-cockpit-muted hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
