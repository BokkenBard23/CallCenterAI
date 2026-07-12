import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useDirtyState } from './useDirtyState';

describe('useDirtyState', () => {
  beforeEach(() => {
    vi.stubGlobal('addEventListener', vi.fn());
    vi.stubGlobal('removeEventListener', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts clean by default', () => {
    const { result } = renderHook(() => useDirtyState());
    expect(result.current.dirty).toBe(false);
  });

  it('markDirty sets dirty=true', () => {
    const { result } = renderHook(() => useDirtyState());
    act(() => result.current.markDirty());
    expect(result.current.dirty).toBe(true);
  });

  it('markClean sets dirty=false', () => {
    const { result } = renderHook(() => useDirtyState(true));
    act(() => result.current.markClean());
    expect(result.current.dirty).toBe(false);
  });

  it('registers beforeunload listener when dirty', () => {
    const addEvent = vi.fn();
    const removeEvent = vi.fn();
    vi.stubGlobal('addEventListener', addEvent);
    vi.stubGlobal('removeEventListener', removeEvent);
    const { result, unmount } = renderHook(() => useDirtyState());
    act(() => result.current.markDirty());
    expect(addEvent).toHaveBeenCalledWith('beforeunload', expect.any(Function));
    unmount();
    expect(removeEvent).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('does not register beforeunload when clean', () => {
    const addEvent = vi.fn();
    vi.stubGlobal('addEventListener', addEvent);
    renderHook(() => useDirtyState(false));
    expect(addEvent).not.toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });
});
