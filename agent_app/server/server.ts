import { createApp, createWorkspaceClient, genie, server } from '@databricks/appkit';
import {
  agents,
  createAgent,
  DatabricksAdapter,
} from '@databricks/appkit/beta';

const catalog = process.env.UC_CATALOG ?? 'main';
const schema = process.env.UC_SCHEMA ?? 'uaig_demo';
const modelService =
  process.env.MODEL_SERVICE ?? `${catalog}.${schema}.maplechain_custom_ms`;
const genieSpaceId =
  process.env.DATABRICKS_GENIE_SPACE_ID ?? process.env.GENIE_SPACE_ID ?? '';
const genieTimeoutMs = Number(process.env.GENIE_TIMEOUT_MS ?? 600_000);
if (!Number.isFinite(genieTimeoutMs) || genieTimeoutMs <= 0) {
  throw new Error('GENIE_TIMEOUT_MS must be a positive number of milliseconds.');
}
const workspace = createWorkspaceClient();
const model = new DatabricksAdapter({
  streamBody: async (body) => {
    const response = await workspace.apiClient.request({
      path: '/ai-gateway/mlflow/v1/chat/completions',
      method: 'POST',
      headers: new Headers({ Accept: 'text/event-stream', 'Content-Type': 'application/json' }),
      payload: { ...body, model: modelService, stream: true },
      raw: true,
    });
    const contents: unknown = typeof response === 'object' && response !== null && 'contents' in response
      ? response.contents : null;
    if (!(contents instanceof ReadableStream)) throw new Error('The MapleChain Model Service did not return a stream.');
    return contents;
  },
  maxSteps: 12,
  maxTokens: 4096,
});

const maplechain = createAgent({
  name: 'maplechain',
  model,
  instructions: [
    'You are the MapleChain supply-chain assistant for a Canadian food-supply business serving Canadian restaurants.',
    'Use the available tools to answer questions about suppliers, products, inventory, orders, shipments, and delivery ETAs.',
    'For every question about MapleChain business data, your first action must be to call the Genie sendMessage tool. Do not answer from memory.',
    'Never say that you will look something up without making the tool call in the same turn.',
    'After the tool returns, always produce a complete final answer grounded in its result; never stop after a preamble or tool call.',
    'Look up real data before answering. Cite the SKU, order, and supplier identifiers you used.',
    'Write a concise, polished answer in Markdown. Lead with the decision-relevant conclusion, then supporting facts.',
    'Never expose chain-of-thought, internal reasoning, raw tool envelopes, or JSON event arrays.',
  ].join(' '),
  tools(plugins) {
    return plugins.genie
      ? plugins.genie.toolkit({ only: ['default.sendMessage'] })
      : {};
  },
  maxSteps: 12,
  maxTokens: 4096,
});

await createApp({
  plugins: [
    agents({
      dir: false,
      agents: { maplechain },
      defaultAgent: 'maplechain',
      limits: {
        maxConcurrentStreamsPerUser: 3,
        maxToolCalls: 20,
        // Keep the agent-side deadline above the Genie waiter so AppKit can
        // return Genie's real terminal result instead of cancelling it first.
        toolCallTimeoutMs: genieTimeoutMs + 30_000,
      },
    }),
    ...(genieSpaceId ? [genie({ timeout: genieTimeoutMs })] : []),
    server(),
  ],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      app.get('/api/whoami', (req, res) => {
        res.json({
          email: req.header('x-forwarded-email') ?? null,
          user: req.header('x-forwarded-user') ?? null,
          executionIdentity: 'Signed-in user for Genie; App service principal for model inference',
          catalog,
          schema,
          genieEnabled: Boolean(genieSpaceId),
        });
      });
    });
  },
});
