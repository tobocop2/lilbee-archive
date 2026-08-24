// Headless opencode workflow harness: agent(), parallel(), batches() over one server.
import { createOpencode } from "@opencode-ai/sdk"

const DEFAULT_MODEL = { providerID: "opencode-go", modelID: "kimi-k3" }

export async function createRunner({ model = DEFAULT_MODEL, port = 4199, config = {} } = {}) {
  const { client, server } = await createOpencode({ hostname: "127.0.0.1", port, config })

  async function agent(text, { schema, title = "wf-agent" } = {}) {
    const session = await client.session.create({ body: { title } })
    const body = { model, parts: [{ type: "text", text }] }
    if (schema) body.format = { type: "json_schema", schema, retryCount: 2 }
    const result = await client.session.prompt({ path: { id: session.data.id }, body })
    const info = result.data.info
    if (info.error) throw new Error(`${info.error.name}: ${info.error.data?.message ?? "agent call failed"}`)
    if (schema) return info.structured
    return (result.data.parts ?? []).filter((p) => p.type === "text").map((p) => p.text).join("")
  }

  return {
    agent,
    parallel: (fns) => Promise.all(fns.map((f) => f())),
    close: () => server.close(),
  }
}

export function batches(items, size) {
  const out = []
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
  return out
}
