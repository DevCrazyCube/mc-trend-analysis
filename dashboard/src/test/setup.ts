/**
 * Test setup: make sure `localStorage` works.
 *
 * Newer Node versions define their own global `localStorage`, which is
 * `undefined` unless Node is started with `--localstorage-file`. It hides the
 * one jsdom would provide, so `localStorage.clear()` throws in a test. When
 * the global is not usable, an in-memory one is installed for the test run.
 */

class MemoryStorage implements Storage {
  private items = new Map<string, string>()

  get length(): number {
    return this.items.size
  }

  clear(): void {
    this.items.clear()
  }

  getItem(key: string): string | null {
    return this.items.has(key) ? (this.items.get(key) as string) : null
  }

  key(index: number): string | null {
    return Array.from(this.items.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.items.delete(key)
  }

  setItem(key: string, value: string): void {
    this.items.set(key, String(value))
  }
}

function usable(storage: unknown): storage is Storage {
  return (
    typeof storage === 'object' &&
    storage !== null &&
    typeof (storage as Storage).clear === 'function' &&
    typeof (storage as Storage).getItem === 'function'
  )
}

let current: unknown
try {
  current = globalThis.localStorage
} catch {
  current = undefined
}

if (!usable(current)) {
  Object.defineProperty(globalThis, 'localStorage', {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  })
}
