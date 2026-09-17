import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Progress,
  ScrollArea,
  Separator,
  Textarea,
  type AgentChatEvent,
  useAgentChat,
} from '@databricks/appkit-ui/react';
import {
  Bot,
  Check,
  Clipboard,
  Database,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  UserRound,
  Wrench,
} from 'lucide-react';

type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string };
type Activity = { id: string; label: string; detail?: string; state: 'running' | 'done' };
type Identity = { email?: string | null; executionIdentity?: string };

const EXAMPLES = [
  'Which suppliers have the highest operational risk?',
  'Check inventory for our most constrained products.',
  'Estimate the delivery ETA for an active restaurant order.',
];

function FormattedAnswer({ text }: { text: string }) {
  const inline = (value: string) => value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    return part;
  });
  const lines = text.split('\n');
  const nodes: ReactNode[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? '';
    const key = `${index}-${line.slice(0, 12)}`;
    if (line.trim().startsWith('|') && lines[index + 1]?.includes('---')) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index]?.trim().startsWith('|')) {
        rows.push((lines[index] ?? '').split('|').slice(1, -1).map((cell) => cell.trim()));
        index += 1;
      }
      index -= 1;
      const [header, , ...body] = rows;
      nodes.push(<table key={key}><thead><tr>{header?.map((cell) => <th key={cell}>{inline(cell)}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{inline(cell)}</td>)}</tr>)}</tbody></table>);
    } else if (line.startsWith('### ')) nodes.push(<h3 key={key}>{inline(line.slice(4))}</h3>);
    else if (line.startsWith('## ')) nodes.push(<h2 key={key}>{inline(line.slice(3))}</h2>);
    else if (line.startsWith('# ')) nodes.push(<h1 key={key}>{inline(line.slice(2))}</h1>);
    else if (/^[-*] /.test(line)) nodes.push(<div className="bullet" key={key}>• <span>{inline(line.slice(2))}</span></div>);
    else if (/^\d+\. /.test(line)) nodes.push(<div className="bullet" key={key}><span>{inline(line)}</span></div>);
    else if (!line.trim()) nodes.push(<div className="line-break" key={key} />);
    else nodes.push(<p key={key}>{inline(line)}</p>);
  }
  return <div className="markdown">{nodes}</div>;
}

function safeToolLabel(name?: string) {
  return (name ?? 'MapleChain tool')
    .replace(/^maplechain_/, '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function AgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [input, setInput] = useState('');
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pendingIdRef = useRef<string | null>(null);

  const onEvent = useCallback((event: AgentChatEvent) => {
    if (event.type === 'response.output_text.delta' && event.delta && pendingIdRef.current) {
      const id = pendingIdRef.current;
      setMessages((items) =>
        items.map((item) =>
          item.id === id ? { ...item, content: item.content + event.delta } : item,
        ),
      );
    }
    if (event.type === 'response.output_item.added' && event.item?.type === 'function_call') {
      const id = event.item.call_id ?? event.item.id ?? crypto.randomUUID();
      setActivities((items) => [
        ...items.map((item) => ({ ...item, state: 'done' as const })),
        { id, label: safeToolLabel(event.item?.name), detail: 'Querying governed MapleChain data', state: 'running' },
      ]);
    }
    if (event.type === 'response.output_item.done' && event.item?.type === 'function_call') {
      setActivities((items) => items.map((item) => ({ ...item, state: 'done' as const })));
    }
  }, []);

  const { content, isStreaming, error, send, reset } = useAgentChat({
    agent: 'maplechain',
    onEvent,
  });

  useEffect(() => {
    fetch('/api/whoami')
      .then((response) => (response.ok ? response.json() : null))
      .then(setIdentity)
      .catch(() => setIdentity(null));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, content, activities]);

  useEffect(() => {
    if (!isStreaming) return;
    const timer = window.setInterval(() => setElapsed((value) => value + 0.1), 100);
    return () => window.clearInterval(timer);
  }, [isStreaming]);

  const status = useMemo(() => {
    if (!isStreaming) return null;
    if (content) return 'Preparing your response';
    if (activities.length) return activities.at(-1)?.detail ?? 'Working with MapleChain data';
    return 'Understanding your request';
  }, [activities, content, isStreaming]);

  async function submit(message: string) {
    const text = message.trim();
    if (!text || isStreaming) return;
    const assistantId = crypto.randomUUID();
    setInput('');
    setActivities([]);
    setElapsed(0);
    setMessages((items) => [
      ...items,
      { id: crypto.randomUUID(), role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '' },
    ]);
    pendingIdRef.current = assistantId;
    await send(text);
    setActivities((items) => items.map((item) => ({ ...item, state: 'done' })));
    pendingIdRef.current = null;
  }

  function newConversation() {
    reset();
    setMessages([]);
    setActivities([]);
    pendingIdRef.current = null;
    setInput('');
    setElapsed(0);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><Sparkles size={18} /></div>
        <div>
          <h1>MapleChain Intelligence</h1>
          <p>Supply chain operations copilot</p>
        </div>
        <div className="topbar-actions">
          <Badge variant="outline"><span className="status-dot" /> Live</Badge>
          <Badge variant="secondary"><UserRound size={13} /> {identity?.email ?? 'Signed in'}</Badge>
          <Button variant="ghost" size="icon" onClick={() => setInspectorOpen((open) => !open)} aria-label="Toggle activity panel">
            {inspectorOpen ? <PanelRightClose /> : <PanelRightOpen />}
          </Button>
        </div>
      </header>

      <aside className="sidebar">
        <Button className="new-chat" onClick={newConversation}><Plus /> New conversation</Button>
        <div className="sidebar-section">
          <span className="eyebrow">Suggested analyses</span>
          {EXAMPLES.map((example) => (
            <button key={example} className="example-link" onClick={() => { void submit(example); }} disabled={isStreaming}>{example}</button>
          ))}
        </div>
        <div className="sidebar-foot">
          <Database size={15} />
          <div><strong>Governed execution</strong><span>{identity?.executionIdentity ?? 'User-scoped Genie access'}</span></div>
        </div>
      </aside>

      <main className="conversation">
        <ScrollArea className="message-scroll">
          <div className="message-column">
            {messages.length === 0 ? (
              <Empty className="welcome-state">
                <EmptyHeader>
                  <div className="welcome-icon"><Bot /></div>
                  <EmptyTitle>What would you like to know?</EmptyTitle>
                  <EmptyDescription>Ask about supplier risk, inventory constraints, restaurant orders, or delivery timing.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="prompt-grid">
                  {EXAMPLES.map((example) => <Button key={example} variant="outline" onClick={() => { void submit(example); }}>{example}</Button>)}
                </EmptyContent>
              </Empty>
            ) : messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="avatar">{message.role === 'user' ? <UserRound /> : <Bot />}</div>
                <div className="message-body">
                  <div className="message-label">{message.role === 'user' ? 'You' : 'MapleChain'}</div>
                  {message.role === 'assistant' && !message.content && isStreaming ? (
                    <div className="thinking"><span /><span /><span /> {status}</div>
                  ) : message.role === 'assistant' ? (
                    <FormattedAnswer text={message.content} />
                  ) : <p>{message.content}</p>}
                  {message.role === 'assistant' && message.content && !isStreaming && (
                    <div className="answer-actions">
                      <Button variant="ghost" size="sm" onClick={() => { void navigator.clipboard.writeText(message.content); }}><Clipboard /> Copy</Button>
                      <span>AI-generated — verify important decisions against source systems.</span>
                    </div>
                  )}
                </div>
              </article>
            ))}
            {error && <Alert variant="destructive"><AlertDescription>{error} Try again or rephrase the request.</AlertDescription></Alert>}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>

        <div className="composer-wrap">
          {isStreaming && <div className="live-status"><Progress value={content ? 76 : activities.length ? 48 : 20} /><span>{status} · {elapsed.toFixed(1)}s</span></div>}
          <form className="composer" onSubmit={(event) => { event.preventDefault(); void submit(input); }}>
            <Textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(input); }
            }} placeholder="Ask MapleChain about your supply chain…" disabled={isStreaming} rows={2} aria-label="Message MapleChain" />
            <Button type="submit" size="icon" disabled={!input.trim() || isStreaming} aria-label="Send message"><Send /></Button>
          </form>
          <p>Enter to send · Shift+Enter for a new line · Data access is governed by Unity Catalog</p>
        </div>
      </main>

      {inspectorOpen && (
        <aside className="inspector">
          <div className="inspector-header"><div><span className="eyebrow">Live activity</span><h2>How this answer was produced</h2></div></div>
          <Separator />
          <Card className="activity-card">
            <CardContent>
              <div className="activity-row"><div className="activity-icon done"><Check /></div><div><strong>Request received</strong><span>Authenticated Databricks App session</span></div></div>
              {activities.map((item) => (
                <div className="activity-row" key={item.id}><div className={`activity-icon ${item.state}`}><Wrench /></div><div><strong>{item.label}</strong><span>{item.detail}</span></div></div>
              ))}
              {isStreaming && !activities.length && <div className="activity-row"><div className="activity-icon running"><Sparkles /></div><div><strong>Understanding request</strong><span>Choosing the appropriate governed tools</span></div></div>}
              {!isStreaming && messages.length > 0 && <div className="activity-row"><div className="activity-icon done"><Check /></div><div><strong>Response complete</strong><span>Sources and identifiers included in the answer</span></div></div>}
            </CardContent>
          </Card>
          <div className="governance-note"><Database /><div><strong>Execution identity</strong><p>Genie runs on behalf of the signed-in user and respects their data permissions. Model inference runs as the App service principal.</p></div></div>
          {messages.length > 0 && !isStreaming && <Button variant="outline" onClick={() => void submit(messages.filter((m) => m.role === 'user').at(-1)?.content ?? '')}><RotateCcw /> Retry last request</Button>}
        </aside>
      )}
    </div>
  );
}
