/**
 * Tests for the event bus implementation (`subscribe` / `emit`).
 * Verifies subscription, multi-listener delivery, unsubscribe, and error isolation.
 */

import { subscribe, emit } from '@/services/eventBus';

describe('eventBus', () => {
  beforeEach(() => {
    // Clear all listeners between tests by accessing internal state
    const listeners = (subscribe as any).listeners || {};
    Object.keys(listeners).forEach((key) => delete listeners[key]);
  });

  it('subscribes to events and receives payloads', () => {
    const listener = jest.fn();

    subscribe('test-event', listener);
    emit('test-event', { data: 'hello' });

    expect(listener).toHaveBeenCalledWith({ data: 'hello' });
  });

  it('supports multiple listeners for same event', () => {
    const listener1 = jest.fn();
    const listener2 = jest.fn();

    subscribe('multi-event', listener1);
    subscribe('multi-event', listener2);

    emit('multi-event', { count: 42 });

    expect(listener1).toHaveBeenCalledWith({ count: 42 });
    expect(listener2).toHaveBeenCalledWith({ count: 42 });
  });

  it('unsubscribes listeners correctly', () => {
    const listener = jest.fn();

    const unsubscribe = subscribe('unsub-event', listener);
    emit('unsub-event', { test: 1 });

    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    emit('unsub-event', { test: 2 });

    expect(listener).toHaveBeenCalledTimes(1); // Still only called once
  });

  it('isolates errors in individual listeners', () => {
    const goodListener = jest.fn();
    const badListener = jest.fn(() => {
      throw new Error('Listener crashed');
    });

    subscribe('error-test', badListener);
    subscribe('error-test', goodListener);

    emit('error-test', { data: 'payload' });

    expect(badListener).toHaveBeenCalled();
    expect(goodListener).toHaveBeenCalled();
  });
});
