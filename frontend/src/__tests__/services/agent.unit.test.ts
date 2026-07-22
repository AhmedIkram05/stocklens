/**
 * agent.unit.test.ts
 *
 * Tests for agent chat service.
 * Uses global.fetch mock for streaming SSE, and jest-fetch-mock for REST endpoints.
 */

import { agentService } from '@/services/agent';
import * as SecureStore from 'expo-secure-store';

const fetchMock = require('jest-fetch-mock');

/**
 * Create a mock Response with a ReadableStream-like body reader
 * for SSE streaming tests.
 */
function mockStreamResponse(chunks: string[]): Response {
  let idx = 0;
  const reader = {
    read: jest.fn(async () => {
      if (idx < chunks.length) {
        const encoder = new TextEncoder();
        return { done: false, value: encoder.encode(chunks[idx++]) };
      }
      return { done: true, value: undefined };
    }),
    cancel: jest.fn(),
    releaseLock: jest.fn(),
  };

  return {
    ok: true,
    status: 200,
    headers: new Headers(),
    body: { getReader: () => reader } as unknown as ReadableStream<Uint8Array>,
  } as Response;
}

// A JWT with exp far in the future (valid token)
const FUTURE_JWT =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTl9.ZwnUZpGyJ8Gf6NtCKQoJGjEHEj_KP2OABcZPq9owKJU';

beforeEach(async () => {
  fetchMock.resetMocks();
  // Set a valid JWT token so api.ts won't throw ApiAuthError
  await SecureStore.setItemAsync('stocklens_access_token', FUTURE_JWT);
  await SecureStore.setItemAsync('stocklens_refresh_token', 'test-refresh-token');
});

describe('agentService.sendMessage (SSE streaming)', () => {
  it('sends a message and parses SSE token events', async () => {
    const sseChunks = [
      'event: token\ndata: "Hello"\n\n',
      'event: token\ndata: " World"\n\n',
      'event: done\ndata: {"conversation_id":"conv-123","full_response":"Hello World"}\n\n',
    ];

    // Mock fetch directly to return a streaming response
    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToken = jest.fn();
      const result = await agentService.sendMessage('Test message', undefined, onToken);

      expect(onToken).toHaveBeenCalledTimes(2);
      expect(onToken).toHaveBeenNthCalledWith(1, 'Hello');
      expect(onToken).toHaveBeenNthCalledWith(2, ' World');
      expect(result.conversationId).toBe('conv-123');
      expect(result.fullResponse).toBe('Hello World');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('fires onToolStart and onToolEnd callbacks', async () => {
    const sseChunks = [
      'event: tool_start\ndata: "get_portfolio_summary"\n\n',
      'event: token\ndata: "Fetching data"\n\n',
      'event: tool_end\ndata: "get_portfolio_summary"\n\n',
      'event: token\ndata: "Done."\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Done."}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToolStart = jest.fn();
      const onToolEnd = jest.fn();
      await agentService.sendMessage('Test', 'conv-1', undefined, onToolStart, onToolEnd);

      expect(onToolStart).toHaveBeenCalledWith('get_portfolio_summary');
      expect(onToolEnd).toHaveBeenCalledWith('get_portfolio_summary', undefined);
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('throws on error SSE event', async () => {
    const sseChunks = ['event: error\ndata: {"error":"Rate limit exceeded"}\n\n'];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      await expect(agentService.sendMessage('Test')).rejects.toThrow('Rate limit exceeded');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('throws on non-200 response', async () => {
    const mockFetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
    } as Response);
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      await expect(agentService.sendMessage('Test')).rejects.toThrow('Chat request failed: 500');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('sends Authorization header with Bearer token', async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue(mockStreamResponse(['event: done\ndata: {"conversation_id":"c-1"}\n\n']));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      await agentService.sendMessage('Hello');

      const call = mockFetch.mock.calls[0];
      expect(call[1].headers['Authorization']).toBe('Bearer ' + FUTURE_JWT);
      expect(call[1].body).toContain('"Hello"');
    } finally {
      global.fetch = originalFetch;
    }
  });
});

describe('agentService.sendMessage traceId', () => {
  it('returns traceId from done event', async () => {
    const sseChunks = [
      'event: token\ndata: "Hello"\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Hello","trace_id":"trace-abc"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const result = await agentService.sendMessage('Test');
      expect(result.traceId).toBe('trace-abc');
      expect(result.conversationId).toBe('conv-1');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('returns empty traceId when done event has no trace_id', async () => {
    const sseChunks = [
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Hello"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const result = await agentService.sendMessage('Test');
      expect(result.traceId).toBe('');
    } finally {
      global.fetch = originalFetch;
    }
  });
});

describe('agentService.submitFeedback', () => {
  it('calls POST /agent/feedback with rating and traceId', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ status: 'ok' }), { status: 200 });

    const result = await agentService.submitFeedback('positive', 'trace-abc');

    expect(result.status).toBe('ok');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/feedback$/),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          rating: 'positive',
          trace_id: 'trace-abc',
          conversation_id: null,
          comment: null,
        }),
      }),
    );
  });

  it('sends optional comment', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ status: 'ok' }), { status: 200 });

    await agentService.submitFeedback('negative', 'trace-xyz', 'Wrong answer');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/feedback$/),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          rating: 'negative',
          trace_id: 'trace-xyz',
          conversation_id: null,
          comment: 'Wrong answer',
        }),
      }),
    );
  });

  it('sends conversation_id when provided', async () => {
    fetchMock.mockResponseOnce(JSON.stringify({ status: 'ok' }), { status: 200 });

    await agentService.submitFeedback('positive', '', undefined, 'conv-123');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/feedback$/),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          rating: 'positive',
          trace_id: null,
          conversation_id: 'conv-123',
          comment: null,
        }),
      }),
    );
  });

  it('returns skipped status when LangSmith disabled', async () => {
    fetchMock.mockResponseOnce(
      JSON.stringify({ status: 'skipped', reason: 'langsmith_disabled' }),
      { status: 200 },
    );

    const result = await agentService.submitFeedback('positive', 'trace-abc');
    expect(result.status).toBe('skipped');
  });
});

describe('agentService REST methods (via apiService mock)', () => {
  it('listConversations returns conversation summaries', async () => {
    const convs = [{ id: '1', title: 'Test', messageCount: 3, createdAt: '', updatedAt: '' }];
    fetchMock.mockResponseOnce(JSON.stringify(convs), { status: 200 });

    const result = await agentService.listConversations();
    expect(result).toHaveLength(1);
    expect(result[0].title).toBe('Test');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/conversations$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('getConversation returns conversation with messages', async () => {
    const data = {
      conversation: { id: '1', title: 'Test', messageCount: 2 },
      messages: [
        { role: 'user', content: 'Hi', createdAt: '' },
        { role: 'assistant', content: 'Hello', createdAt: '' },
      ],
    };
    fetchMock.mockResponseOnce(JSON.stringify(data), { status: 200 });

    const result = await agentService.getConversation('1');
    expect(result.messages).toHaveLength(2);
    expect(result.messages[0].role).toBe('user');
  });

  it('deleteConversation sends DELETE', async () => {
    fetchMock.mockResponseOnce('', { status: 204 });

    await agentService.deleteConversation('1');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/agent\/conversations\/1$/),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
});

describe('agentService.sendMessage edge cases', () => {
  it('handles tool_end with object format and base64 decoded result', async () => {
    const sseChunks = [
      'event: tool_start\ndata: "get_portfolio_summary"\n\n',
      'event: tool_end\ndata: {"tool_name":"get_portfolio_summary","result":"eyJ0ZXN0IjogInZhbHVlIn0="}\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Done"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToolEnd = jest.fn();
      await agentService.sendMessage('Test', 'conv-1', undefined, undefined, onToolEnd);

      expect(onToolEnd).toHaveBeenCalledWith('get_portfolio_summary', { test: 'value' });
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('handles tool_end with invalid base64 gracefully', async () => {
    const sseChunks = [
      'event: tool_end\ndata: {"tool_name":"get_portfolio_summary","result":"bm90IGpzb24="}\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Done"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToolEnd = jest.fn();
      await agentService.sendMessage('Test', 'conv-1', undefined, undefined, onToolEnd);

      // Invalid base64 leaves parsedResult undefined
      expect(onToolEnd).toHaveBeenCalledWith('get_portfolio_summary', undefined);
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('handles empty token from server', async () => {
    const sseChunks = [
      'event: token\ndata: ""\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":""}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToken = jest.fn();
      await agentService.sendMessage('Test', undefined, onToken);

      expect(onToken).toHaveBeenCalledWith('');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('works without token callback', async () => {
    const sseChunks = [
      'event: token\ndata: "Hello"\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Hello"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const result = await agentService.sendMessage(
        'Test',
        'conv-1',
        undefined,
        undefined,
        undefined,
      );
      expect(result.conversationId).toBe('conv-1');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('handles multiple tool_start/tool_end pairs in sequence', async () => {
    const sseChunks = [
      'event: tool_start\ndata: "tool1"\n\n',
      'event: tool_end\ndata: "tool1"\n\n',
      'event: token\ndata: "First result"\n\n',
      'event: tool_start\ndata: "tool2"\n\n',
      'event: tool_end\ndata: "tool2"\n\n',
      'event: token\ndata: "Second result"\n\n',
      'event: done\ndata: {"conversation_id":"conv-1","full_response":"Results"}\n\n',
    ];

    const mockFetch = jest.fn().mockResolvedValue(mockStreamResponse(sseChunks));
    const originalFetch = global.fetch;
    global.fetch = mockFetch;

    try {
      const onToolStart = jest.fn();
      const onToolEnd = jest.fn();
      await agentService.sendMessage('Test', undefined, undefined, onToolStart, onToolEnd);

      expect(onToolStart).toHaveBeenCalledTimes(2);
      expect(onToolStart).toHaveBeenNthCalledWith(1, 'tool1');
      expect(onToolStart).toHaveBeenNthCalledWith(2, 'tool2');
      expect(onToolEnd).toHaveBeenCalledTimes(2);
      expect(onToolEnd).toHaveBeenNthCalledWith(1, 'tool1', undefined);
      expect(onToolEnd).toHaveBeenNthCalledWith(2, 'tool2', undefined);
    } finally {
      global.fetch = originalFetch;
    }
  });
});
