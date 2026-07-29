# Per-GPU ingest workers

One lilbee process saturates one GPU. Today a single process is asked to drive
every card in the box, and it cannot. This makes the worker the unit of scaling
instead of the host.

## Problem

Bulk ingest does not scale with hardware. Measured 2026-07-29 on RunPod H100 SXM
with the production embedder (Qwen3-Embedding-8B-Q8_0, 4096-dim), 80k MS MARCO
passages, fresh index per run, GPU sampled every 2s:

| configuration | docs/s | GPU util |
|---|---|---|
| 1xH100, 1 process | 59-60 | **94%** |
| 4xH100, 1 process | 161.9 | ~50% |
| 8xH100, 1 process | 104.6 | 22% |
| 8xH100, 2 processes | **152.1** | 34% |
| 8xH100, 4 processes | 144.7 | 31% |
| 8xH100, 2 processes (repeat) | 147.3 | 33% |

The noise floor is ~3%, so four processes is not an improvement over two.

Two facts follow. **A single card is already saturated** at 94% SM, so lilbee is
not slow; it is sized for one GPU. And **adding cards makes things worse**: eight
cards peak at 152 where four reach 161.9, and at the default single process eight
cards deliver 104.6 against four cards' 161.9. Buying GPUs currently buys
negative throughput.

Cost follows utilisation:

| pod | card-hours for 8.8M | cost at $2.69/card-hr |
|---|---|---|
| 1xH100 | 41.6 | **~$112** |
| 4xH100 | 60.6 | ~$163 |
| 8xH100 | 129 | ~$348 |

Every other lever is measured dead: per-card throughput is GPU-bound at 94% SM,
`--parallel` tuning is optimal, raising admission is worse at every level, embed
coalescing regressed (0.42-0.91x), worker fragment writes regressed (214 -> 167),
`httpx` pool limits are a no-op, and llama-swap's `concurrencyLimit` is a no-op.

## Approach

Run one lilbee process per GPU, each pinned with `CUDA_VISIBLE_DEVICES`, each
owning its own data root and its own slice of the corpus. Scaling is then a
worker count, and a host is just a place workers happen to live. The same unit
serves single-host and multi-host without a second mechanism.

Three of the four sharing concerns are already satisfied and need no work:

- **Model file**: `models_dir` defaults to a global location, so all workers read
  one copy.
- **Host RAM**: weights are mmapped on local disk, so the page cache holds one
  copy mapped into every engine.
- **Device isolation**: lilbee already masks its device view by
  `CUDA_VISIBLE_DEVICES`, so a pinned worker sees one GPU and places one replica.

There is a hard constraint attached: `planning.py` switches to `--no-mmap` when
weights sit on a network filesystem, which would malloc a private copy per
worker. **Models must live on local disk, never a mounted network volume**, or N
workers cost N times the host RAM.

VRAM holds one copy of the weights per card. That is correct and unavoidable;
it is what data-parallel inference is.

## What blocks it today

A validation run on 8xH100 (2026-07-29) launched eight pinned workers over 10k
passages each. **Seven never started an engine.** One card sat at 95% and 9869
MiB; the other seven stayed at 0%/0 MiB for the whole run. All eight workers
advanced in lockstep to 79% of planning and stopped, on a box at load average
2.65 out of 224 vCPU. Not CPU contention, not GPU contention.

The worker logs name the cause:

```
RuntimeWarning: lancedb fork support is experimental: the internal async runtime
has been reset in the forked child, but a small chance of deadlock remains if
other state was mid-operation at fork time. The 'forkserver' or 'spawn'
multiprocessing start method is likely a safer alternative.
```

lilbee forks its subprocess pools while LanceDB's async runtime is live. The one
worker that escaped was the data root used earlier for `lilbee model pull`, so it
had warm fleet state and took a different path.

Four changes are required, in dependency order.

### 1. Fork safety (blocking)

Switch ingest's process pool to `forkserver` or `spawn`, as the runtime warning
itself recommends. Until this lands, N concurrent lilbee processes on one host
deadlock and the architecture cannot be measured at all.

### 2. Ingest must not plan roles it will not use (blocking for cleanliness,
and independently a product requirement)

Every worker logged `Skipping chat server: model 'Qwen/Qwen3-0.6B-GGUF/...' is
not installed`. The fleet plans placement across `CHAT`, `EMBED`, `RERANK` and
`VISION` regardless of what the caller needs. An ingest needs `EMBED`, plus
`VISION` only when OCR is enabled.

The broader requirement: **a chat model is optional**. Ingest, the TUI and the
plugin must all work fully without one; only chat itself should require it, and
its absence should surface as a clear message on the chat surface rather than a
warning during unrelated work. Placement should be scoped to the roles a command
actually uses.

### 3. Host-share awareness

`init_worker` already divides CPU and admission across lilbee's own worker
processes, but nothing tells a lilbee process that seven siblings share the box.
Each sizes its pools from the whole machine. Add an explicit share
(`LILBEE_HOST_WORKERS` or equivalent) that divides the planning pool, the
extraction pool and the admission budget.

This did not bite in the failed run (load 2.65 of 224) but will the moment fork
safety lets all eight reach the embed phase.

### 4. Port allocation race

Ports are claimed by binding a socket, then released before llama-server binds
them. Concurrent workers can pick the same port in that window. The validation
run papered over it with a 6-second stagger. A filesystem-level reservation, or
letting the caller pass a port base, removes the race rather than narrowing it.

### Separately: planning is slow

Planning ran at 16-30 files/s per worker on an idle box: roughly eight minutes of
preamble per 10k files. This is independent of the per-GPU work and affects every
ingest, including single-process. It deserves its own investigation rather than
being folded in here.

## Orchestration

Orchestration stays outside lilbee. lilbee's contract is "ingest this slice onto
this GPU"; deciding how many workers exist, where they run and what happens when
one dies is an operations concern.

The workers are identical and independent, which keeps the orchestrator small: a
work list, a launcher, and a collector. `runpodctl` has proven reliable for
provisioning, landing 8xH100 first try repeatedly, where SkyPilot's RunPod
catalog has not. `dstack` is the strongest managed alternative and has
first-party RunPod support if hand-rolled provisioning becomes a burden.

Ray Data is the industry-standard answer for distributed embedding, but it would
replace lilbee's ingest pipeline rather than use it. That is a different project.

## Storage and merge

Each worker writes its own LanceDB, so results are combined by the existing
partitioned merge, which verifies completeness and embedder identity, streams
rather than materialising, and rebuilds the ANN and BM25 indexes corpus-wide.
Sharding by worker rather than by host means more shards, which makes that
merge's guardrails more load-bearing, not less.

A single object-store-backed table with N writers was considered and rejected:
Lance requires a commit store for safe concurrent writes on S3, and there are
reports of commit-retry exhaustion and stuck tables even with a single writer.
Optimistic concurrency across dozens of continuously committing workers is the
wrong shape.

If object storage is wanted for shard hand-off, SeaweedFS is the pick over MinIO,
whose community edition was archived in February 2026.

## Proof

The architecture is a throughput claim, so reading it proves nothing. It is
accepted only if all of the following hold.

**Scaling.** On one 8xH100 host, N pinned workers over a fixed corpus, N = 1, 2,
4, 8, GPU sampled throughout. Aggregate throughput must rise roughly linearly and
per-card utilisation must stay near the 94% a single card reaches alone. The
target is ~470 docs/s at N=8 against the 152 one process manages on identical
hardware. A repeat at the best N establishes the noise floor; without it a delta
is not interpretable.

**No regression.** N=1 must match the current single-process figure on the same
hardware. If the fork-safety change slows the ordinary path, that is a finding.

**Correctness.** The N shards merged must equal a single-host index over the same
corpus: identical row counts, identical source-path sets, one `_meta` row, and
chunk text equal when joined on id. Vectors are compared per id and must fall
within the drift a single host shows against its own re-run, which is the only
meaningful floor since embeddings are not deterministic.

**Accuracy.** MS MARCO ships qrels, so this is measured rather than argued:
MRR@10 and nDCG@10 over the dev queries against the merged index and against a
single-host index. Merged must fall inside the single-host-versus-itself
interval.

**The merge tail.** Colocation plus index rebuild is constant regardless of
worker count, so it caps the achievable speedup. Measure it at three corpus sizes
and fit the curve rather than extrapolating from one point.

## Risks

The largest is that fork safety does not fully explain the deadlock and workers
still fail to start concurrently. The N=2 case is the cheap probe: if two pinned
workers run cleanly, the mechanism is understood.

Second, `spawn`/`forkserver` costs more per worker start than `fork` and requires
picklable state. That may show up as slower startup on the ordinary single-
process path, which the no-regression check exists to catch.

Third, per-GPU workers multiply shard count, so an 8-card host produces eight
shards rather than one. The merge is hardened but has never run at that width on
real indexes.
