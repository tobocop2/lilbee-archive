import { createOpencode } from "@opencode-ai/sdk"

const SCHEMA = { type: "object", required: ["ok"], properties: { ok: { type: "boolean" } } }
const MODEL = { providerID: "opencode-go", modelID: "kimi-k3" }

const { client, server } = await createOpencode({ hostname: "127.0.0.1", port: 4199 })

async function probe(name, { text, schema, agent }) {
  const session = await client.session.create({ body: { title: `probe:${name}` } })
  const body = { model: MODEL, parts: [{ type: "text", text }] }
  if (schema) body.format = { type: "json_schema", schema }
  if (agent) body.agent = agent
  try {
    const r = await client.session.prompt({ path: { id: session.data.id }, body })
    const info = r.data.info
    if (info.error) return console.log(`${name}: FAIL ${info.error.name}: ${info.error.data?.message}`)
    console.log(`${name}: OK structured=${JSON.stringify(info.structured ?? null)}`)
  } catch (e) {
    console.log(`${name}: THROW ${e.message.slice(0, 120)}`)
  }
}

try {
  await probe("1-schema-no-tools", { text: "Return ok=true.", schema: SCHEMA })
  await probe("2-read-no-schema", { text: "Read src/lilbee/core/results.py with the read tool and reply with one short sentence about it." })
  await probe("3-read-with-schema", { text: "Read src/lilbee/core/results.py with the read tool, then return ok=true.", schema: SCHEMA })
  await probe("4-read-schema-explore", { text: "Read src/lilbee/core/results.py, then return ok=true.", schema: SCHEMA, agent: "explore" })
} finally {
  server.close()
}
