// ══════════════════════════════════════════════════════════════════════════════
// Test Setup - Global mocks and configuration
// ══════════════════════════════════════════════════════════════════════════════

import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// ══════════════════════════════════════════════════════════════════════════════
// Cleanup after each test
// ══════════════════════════════════════════════════════════════════════════════

afterEach(() => {
  cleanup();
});

// ══════════════════════════════════════════════════════════════════════════════
// Global Mocks
// ══════════════════════════════════════════════════════════════════════════════

// Mock requestAnimationFrame
globalThis.requestAnimationFrame = vi.fn((cb) => setTimeout(cb, 0));
globalThis.cancelAnimationFrame = vi.fn((id) => clearTimeout(id));

// Mock IntersectionObserver
globalThis.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock ResizeObserver
globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock WebGLRenderingContext
const mockWebGLRenderingContext = {
  canvas: document.createElement('canvas'),
  getParameter: vi.fn().mockReturnValue('Mock GPU'),
  getExtension: vi.fn().mockReturnValue(null),
  createShader: vi.fn(),
  shaderSource: vi.fn(),
  compileShader: vi.fn(),
  createProgram: vi.fn(),
  attachShader: vi.fn(),
  linkProgram: vi.fn(),
  useProgram: vi.fn(),
  getAttribLocation: vi.fn().mockReturnValue(0),
  getUniformLocation: vi.fn().mockReturnValue({}),
  enableVertexAttribArray: vi.fn(),
  vertexAttribPointer: vi.fn(),
  uniform1f: vi.fn(),
  uniform2f: vi.fn(),
  uniform3f: vi.fn(),
  uniform4f: vi.fn(),
  uniformMatrix4fv: vi.fn(),
  drawArrays: vi.fn(),
  drawElements: vi.fn(),
  clear: vi.fn(),
  clearColor: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  viewport: vi.fn(),
};

HTMLCanvasElement.prototype.getContext = vi.fn().mockImplementation((type) => {
  if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') {
    return mockWebGLRenderingContext;
  }
  return null;
});

// Mock AudioContext
globalThis.AudioContext = vi.fn().mockImplementation(() => ({
  state: 'running',
  currentTime: 0,
  destination: {},
  resume: vi.fn(),
  suspend: vi.fn(),
  close: vi.fn(),
  createOscillator: vi.fn().mockReturnValue({
    type: 'sine',
    frequency: { value: 440 },
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    disconnect: vi.fn(),
    onended: null,
  }),
  createGain: vi.fn().mockReturnValue({
    gain: {
      value: 1,
      setValueAtTime: vi.fn(),
      linearRampToValueAtTime: vi.fn(),
      setTargetAtTime: vi.fn(),
    },
    connect: vi.fn(),
    disconnect: vi.fn(),
  }),
}));

// Mock window.URL.createObjectURL
globalThis.URL.createObjectURL = vi.fn().mockReturnValue('blob:mock-url');
globalThis.URL.revokeObjectURL = vi.fn();

// ══════════════════════════════════════════════════════════════════════════════
// Console suppression (optional)
// ══════════════════════════════════════════════════════════════════════════════

// Uncomment to suppress console logs during tests
// const originalConsoleLog = console.log;
// console.log = (...args) => {
//   // Suppress non-error logs
// };

// const originalConsoleError = console.error;
// console.error = (...args) => {
//   // Keep errors visible
//   originalConsoleError(...args);
// };
