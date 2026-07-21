/**
 * agent.ts
 *
 * Agent chat service with SSE streaming for the LangGraph ReAct agent.
 * Uses raw fetch + ReadableStream for streaming response parsing,
 * instead of EventSource which has limited React Native support.
 */

import { apiService } from './api';

const API_BASE = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AgentMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: any[];
  toolResults?: any[];
  createdAt: string;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface FeedbackResponse {
  status: string;
  reason?: string;
}

// ── Service ───────────────────────────────────────────────────────────────────

export const agentService = {
  /**
   * Send a message to the agent and stream the response via SSE.
   *
   * Uses fetch + ReadableStream for cross-platform React Native support.
   * The SSE parser tracks `event:` lines and associates them with the
   * subsequent `data:` line for correct event-type routing.
   */
  async sendMessage(
    message: string,
    conversationId?: string,
    onToken?: (token: string) => void,
    onToolStart?: (toolName: string) => void,
    onToolEnd?: (toolName: string, result?: any) => void,
  ): Promise<{ conversationId: string; fullResponse: string; traceId: string }> {
    const token = await apiService.ensureValidAccessToken();
    if (!token) {
      throw new Error('Session expired. Please log in again.');
    }
    const response = await fetch(`${API_BASE}/agent/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message, conversation_id: conversationId || null }),
    });

    if (!response.ok) {
      throw new Error(`Chat request failed: ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullResponse = '';
    let resolvedConversationId = conversationId || '';
    let resolvedTraceId = '';
    let currentEvent = ''; // Track current SSE event type

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          switch (currentEvent) {
            case 'token':
              fullResponse += data;
              onToken?.(data);
              break;
            case 'tool_start':
              onToolStart?.(data);
              break;
            case 'tool_end': {
              // tool_end data is either:
              //   (old) string tool name — backward compat
              //   (new) { tool_name, result: base64-encoded JSON }
              let toolName: string;
              let parsedResult: any = undefined;
              if (typeof data === 'string') {
                toolName = data;
              } else {
                toolName = data.tool_name ?? 'unknown';
                if (data.result) {
                  try {
                    const decoded = atob(data.result);
                    parsedResult = JSON.parse(decoded);
                  } catch (_e) {
                    // If base64 decode or JSON parse fails, skip result
                  }
                }
              }
              onToolEnd?.(toolName, parsedResult);
              break;
            }
            case 'done':
              resolvedConversationId = data.conversation_id || resolvedConversationId;
              resolvedTraceId = data.trace_id || '';
              break;
            case 'error':
              throw new Error(data.error);
          }
          currentEvent = ''; // Reset after consuming
        }
      }
    }

    return { conversationId: resolvedConversationId, fullResponse, traceId: resolvedTraceId };
  },

  async listConversations(): Promise<ConversationSummary[]> {
    return apiService.get('/agent/conversations');
  },

  async getConversation(
    conversationId: string,
  ): Promise<{ conversation: ConversationSummary; messages: AgentMessage[] }> {
    return apiService.get(`/agent/conversations/${conversationId}`);
  },

  async deleteConversation(conversationId: string): Promise<void> {
    return apiService.delete(`/agent/conversations/${conversationId}`);
  },

  async submitFeedback(
    rating: string,
    traceId: string,
    comment?: string,
  ): Promise<FeedbackResponse> {
    return apiService.post('/agent/feedback', {
      rating,
      trace_id: traceId,
      comment: comment || null,
    });
  },
};
