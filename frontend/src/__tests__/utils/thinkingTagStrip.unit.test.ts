/**
 * Unit tests for thinking-tag stripping regex patterns.
 *
 * These regexes are used in the AgentChatScreen post-stream safety net
 * to strip Amazon Nova <thinking> reasoning tags from final response text.
 * The same logic is mirrored from the backend `_strip_thinking_tags`.
 */

function stripThinkingTags(text: string): string {
  return text
    .replace(/<thinking>[\s\S]*?<\/thinking>\s*/g, '')
    .replace(/<thinking\b[\s\S]*/g, '')
    .replace(/\s*<\/thinking>/g, '')
    .trim();
}

describe('thinking tag stripping regex', () => {
  it('strips complete <thinking>...</thinking> pairs', () => {
    expect(stripThinkingTags('<thinking>reasoning</thinking>Hello world')).toBe('Hello world');
  });

  it('strips complete pairs with surrounding text', () => {
    expect(stripThinkingTags('Before <thinking>inner</thinking> After')).toBe('Before After');
  });

  it('strips multi-line thinking blocks', () => {
    const text = '<thinking>line1\nline2\nline3</thinking>\nFinal answer.';
    expect(stripThinkingTags(text)).toBe('Final answer.');
  });

  it('strips trailing whitespace after closed tag', () => {
    expect(stripThinkingTags('<thinking>a</thinking>   \nContent')).toBe('Content');
  });

  it('strips unclosed <thinking> tag to end of string', () => {
    const text = '<thinking>The same portfolio summary is still being returned';
    expect(stripThinkingTags(text)).toBe('');
  });

  it('strips unclosed <thinking with no > to end of string', () => {
    const text = '<thinking partial reasoning without closing bracket';
    expect(stripThinkingTags(text)).toBe('');
  });

  it('strips <thinking across multiple lines with no close', () => {
    const text = '<thinking\nmulti\nline\nunclosed reasoning';
    expect(stripThinkingTags(text)).toBe('');
  });

  it('strips stray </thinking> tags', () => {
    expect(stripThinkingTags('Hello </thinking> world')).toBe('Hello world');
  });

  it('handles text with no thinking tags', () => {
    expect(stripThinkingTags('Normal response without any tags.')).toBe(
      'Normal response without any tags.',
    );
  });

  it('handles empty string', () => {
    expect(stripThinkingTags('')).toBe('');
  });

  it('handles mixed content with multiple thinking tags', () => {
    const text = '<thinking>first</thinking>A<thinking>second</thinking>B';
    // Regex strips the tags without inserting spaces — adjacent chars stay adjacent
    expect(stripThinkingTags(text)).toBe('AB');
  });

  it('handles <thinking> at the very end of string without close', () => {
    expect(stripThinkingTags('Some text <thinking')).toBe('Some text');
  });

  it('does not strip <thinking embedded in a word (no word boundary)', () => {
    // \b requires word boundary after "thinking" — "g" and "w" are both word chars,
    // so <thinkingworld has no boundary and the regex does NOT match
    const text = 'Hello<thinkingworld';
    expect(stripThinkingTags(text)).toBe('Hello<thinkingworld');
  });

  it('strips thinking tag that appears after normal content', () => {
    const text = 'Answer is 42.<thinking>Actually let me reconsider</thinking>Final answer: 42.';
    // Regex removes <thinking>...</thinking>\s* — no space between "42." and "Final"
    expect(stripThinkingTags(text)).toBe('Answer is 42.Final answer: 42.');
  });
});
