/**
 * EventBus
 *
 * Lightweight pub/sub helper for cross-component communication.
 */

/**
 * Listener function type
 *
 * @param payload - Optional event data (any type)
 */
type Listener = (payload?: any) => void;

/**
 * Internal registry of event listeners
 *
 * Map of event name → Set of listener functions
 */
const listeners: Record<string, Set<Listener>> = {};

/**
 * Subscribe to an event
 *
 * @param event - Event name (e.g., 'receipts-changed')
 * @param fn - Listener function to call when event is emitted
 * @returns Unsubscribe function (call to remove listener)
 *
 * Features:
 * - Automatically creates listener set if event doesn't exist
 * - Unsubscribe cleans up empty listener sets
 * - Can subscribe multiple listeners to same event
 */
export const subscribe = (event: string, fn: Listener) => {
  if (!listeners[event]) listeners[event] = new Set();
  listeners[event].add(fn);
  return () => {
    listeners[event].delete(fn);
    if (listeners[event].size === 0) delete listeners[event];
  };
};

/**
 * Emit an event to all subscribed listeners
 *
 * @param event - Event name (e.g., 'receipts-changed')
 * @param payload - Optional data to pass to listeners
 *
 * Features:
 * - Calls all listeners synchronously in registration order
 * - Catches and logs listener errors (prevents one bad listener from breaking others)
 * - No-op if no listeners registered for event
 *
 * Usage:
 * emit('receipts-changed', { userId: auth.currentUser.uid });
 */
export const emit = (event: string, payload?: any) => {
  const set = listeners[event];
  if (!set) return;
  for (const fn of Array.from(set)) {
    try {
      fn(payload);
    } catch (e) {}
  }
};

export default { subscribe, emit };
