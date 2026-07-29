# Per-GPU ingest workers

One lilbee process saturates one GPU. Asked to drive eight it reaches a third of
them. This makes the worker the unit of scaling instead of the host.

Everything marked *measured* comes from RunPod H100 SXM pods on 2026-07-29 with
the production embedder (Qwen3-Embedding-8B-Q8_0, 4096-dim) over 80k MS MARCO
passages, fresh index per run, GPU sampled every 2s. Those pods no longer exist,
so the numbers are measurements on record, not facts reproducible from this
repository. Claims about lilbee's own behaviour cite source and are checkable.

## Problem

Bulk ingest does not scale with hardware.

| configuration | docs/s | GPU util |
|---|---|---|
| 1xH100, 1 process | 59-60 | **94%** |
| 4xH100, 1 process | 161.9 | ~50% |
| 8xH100, 1 process | 104.6 | 22% |
| 8xH100, 2 processes | **152.1** | 34% |
| 8xH100, 4 processes | 144.7 | 31% |
| 8xH100, 2 processes (repeat) | 147.3 | 33% |

Each row is one run except the repeat, which differed from its twin by 3%. That
is the only evidence of run-to-run variance here; it is not a replicated noise
floor.

A single card is already saturated at 94% SM, so lilbee is not slow. And scaling
turns negative past four cards: eight cards peak at 152.1 where four reach 161.9,
and at the default single process eight cards deliver 104.6 against four cards'
161.9.

The one-to-four numbers complicate the "one process, one GPU" framing. A single
process does drive four cards to 161.9, roughly 2.7 cards' worth. The shape is
that a process scales to a few cards and then collapses, not that it is strictly
limited to one.

Every lever inside the embed phase is measured dead: per-card throughput is
GPU-bound at 94% SM, `--parallel` tuning is optimal, raising admission is worse
at every level, embed coalescing regressed (0.42-0.91x), worker fragment writes
regressed (214 -> 167), `httpx` pool limits are a no-op, and llama-swap's
`concurrencyLimit` is a no-op.

## What this buys

Wall clock, not money. Eight workers at the per-card rate would put 8.8M passages
at roughly 5 hours instead of ~41 card-hours on one card, at approximately the
same total card-hours. If cost were the goal the answer would be one H100, not
eight.

The 8.8M figures are extrapolated from an 80k run; size-invariance is unverified.

| pod | card-hours for 8.8M | cost at $2.69/card-hr |
|---|---|---|
| 1xH100 | ~41 | ~$110 |
| 4xH100 | ~61 | ~$163 |
| 8xH100 | ~129 | ~$348 |

## Approach

Run one lilbee process per GPU, each pinned with `CUDA_VISIBLE_DEVICES`, each
owning its own data root and its own slice of the corpus. Scaling becomes a
worker count, and a host is just where workers live.

Sharing is mostly already handled:

- **Model file**: `models_dir` defaults to a global location, so all workers read
  one copy.
- **Host RAM**: `--no-mmap` is chat-only and additionally gated on the weights
  fitting a fraction of RAM (`planning.py:1523`, `_chat_no_mmap`), so an embed
  fleet always mmaps and N workers share one page-cache copy. An earlier draft
  claimed models must stay off network filesystems to avoid N private copies;
  that was wrong for embed.
- **Device view**: lilbee masks device enumeration, VRAM sizing and replica-count
  resolution by `CUDA_VISIBLE_DEVICES`.

VRAM holds one copy of the weights per card, which is what data-parallel
inference is.

**Device masking is not process isolation.** The engine state directory comes
from `default_state_dir()` (`core/system.py:62`), which is machine-wide
(`~/.local/state/lilbee` on Linux) and independent of `LILBEE_DATA`. Every worker
on a host shares one engine slot regardless of pinning. This is the leading
suspect for the failure below.

## What blocks it today

A validation run on 8xH100 launched eight pinned workers over 10k passages each.
**Seven never started an engine.** One card sat at 95% and 9869 MiB; the other
seven stayed at 0%/0 MiB. The box was at load average 2.65 of 224 vCPU, so it was
neither CPU nor GPU contention.

The cause is **not established**. Two explanations were considered and rejected
on evidence:

- *Fork unsafety.* The worker logs carry lancedb's "fork support is experimental"
  RuntimeWarning, and an earlier draft treated it as the cause and proposed
  switching the pool to spawn. The ingest pool is **already** spawn
  (`workers.py:271`, `mp_context=multiprocessing.get_context("spawn")`, whose
  docstring says fork "would inherit LanceDB"). The warning comes from another
  fork site, most likely the `preexec_fn` fork in the engine spawn path where the
  child execs immediately. That fix would have been a no-op.
- *Lockstep as deadlock evidence.* All eight workers last reported at 79% of
  planning. Plan shards ramp 256/512/1024/2048/4096, giving cumulative boundaries
  `[256, 768, 1792, 3840, 7936, 10000]`, and the observed progress lines were
  1793, 3841 and 7937 — boundary+1 each time. Identical stopping points are what
  deterministic sharding produces, not evidence of a shared lock.

The **leading hypothesis** is engine-slot collision: with a machine-wide state
directory, and a port picker that claims a port by binding a socket then releases
it before llama-server binds (`swap_manager.py`, `_pick_free_ports`), a worker can
health-check a sibling's proxy, find a live fleet, and adopt it. That predicts
exactly what was seen — one engine serving one card while seven workers believe a
fleet is already running.

It is a hypothesis. The experiment that settles it is free (see Proof).

## Changes, in dependency order

### 1. Engine identity per worker (blocking)

Give each worker its own engine slot and port range, keyed off the data root or
an explicit worker index rather than a machine-wide directory. Disjoint port
ranges per worker index cannot race by construction and need no coordination,
which is simpler than a filesystem reservation.

Until this lands, N concurrent lilbee processes on one host cannot be measured.

### 2. Host-share awareness (blocking only if measured)

`init_worker` divides CPU and admission across lilbee's own worker processes, but
nothing tells a lilbee process that siblings share the box, so each sizes its CPU
pools from the whole machine. Admission largely self-divides under pinning since
the fleet-derived term comes from the masked device view; CPU pools are the gap.

The launcher already sets `CUDA_VISIBLE_DEVICES` per worker, so it can set the
existing pool-sizing environment variables too. Add a new knob only if
oversubscription is measured at N=8. This did not bite in the failed run (load
2.65 of 224).

### 3. Scope placement to declared roles (not blocking)

The fleet sizes CHAT, EMBED, RERANK and VISION on an ingest. When the chat model
is absent this costs one warning per process and nothing else, so it did not
contribute to the failure. The real cost is on a box where those models *are*
installed: they are sized and charged VRAM ahead of the elastic embed replicas,
taking replicas from the only role the run uses.

Separately: **a chat model should be optional**. Ingest and the TUI must work
fully without one, and its absence should surface on the chat surface rather than
during unrelated work. A product requirement, tracked on its own; it does not
block per-GPU workers.

### Planning cost, unresolved

The plan-progress line reports files planned over wall-clock since the plan
stream opened, and the stream is pull-driven, so the reported rate is coupled to
ingest throughput rather than being a pure planning cost. The 16-30 files/s seen
in the failed run cannot be read as "planning is slow" on its own.

There is a real cost underneath: a first ingest hashes every file's contents
(`_classify_file_change`), so the whole corpus is read off disk. Whether that
matters at 8.8M is unmeasured. Tracked separately.

## Orchestration

Orchestration stays outside lilbee. For the single-host case it is `runpodctl`,
a shell loop over worker indices, and the existing merge — **no orchestrator is
being built**. If a multi-host fleet later justifies one, `dstack` has
first-party RunPod support and is the strongest managed option.

Ray Data is the industry-standard answer for distributed embedding, but it would
replace lilbee's ingest pipeline rather than use it. Different project.

## Storage and merge

Each worker writes its own LanceDB, combined by the existing partitioned merge on
`feat/partitioned-ingest`. It verifies the shard set is complete (every declared
index present exactly once) and that no shard was truncated after its ingest,
that all shards share one embedder identity, streams rather than materialising,
and rebuilds the ANN and BM25 indexes corpus-wide because BM25 IDF is a
corpus-wide statistic.

A single object-store-backed table with N writers was rejected. Lance uses
optimistic concurrency on object storage, and lancedb#3086 reports "Too many
concurrent writers" with a bounded retry count; dozens of continuously committing
workers is the wrong shape for it.

Per-GPU sharding multiplies shard count: an 8-card host produces 8 shards, a
four-host fleet 32. Two consequences worth stating rather than assuming away. The
merge host needs roughly the whole corpus on one filesystem to colocate them, and
the merge is all-or-nothing with no resume, so one failed shard costs the whole
merge.

## Proof

The architecture is a throughput claim, so reading it proves nothing. The
validation ladder is deliberately cheapest-first; each rung can kill the design
before the next is paid for.

**Rung 0, free, no GPU.** Start two lilbee processes with different `LILBEE_DATA`
on any machine and check whether the second adopts the first's engine slot. This
is a `default_state_dir()` question, not a GPU question. It confirms or kills the
engine-collision hypothesis for nothing.

**Rung 1, ~$1.50.** Two pinned workers on a 2xH100 pod over 20k passages. Two
questions at once: do both start their own engine, and is aggregate throughput
about twice the single-card rate at near-94% utilisation? If it lands near 118
docs/s the architecture scales and eight cards is arithmetic. If it lands near 80
at 40%, the design is dead and the 8-card run was never worth buying. Use the 8B
production model, not a small one: a 0.6B embedder on fast cards is client-bound
rather than GPU-bound, and generalising across regimes is how three earlier
proposals went wrong.

**Rung 2, the full sweep**, only if rung 1 passes: N = 1, 2, 4, 8 on one 8xH100
host with a repeat at the best N. At that point it is closer to a production run
than a validation.

**No regression.** N=1 must match the current single-process figure on the same
hardware.

**Correctness.** The N shards merged must equal a single-host index over the same
corpus: identical row counts, identical source-path sets, one `_meta` row, chunk
text equal when joined on id, and vectors within the drift a single host shows
against its own re-run, which is the only meaningful floor since embeddings are
not deterministic.

**The merge tail.** Colocation plus index rebuild is constant regardless of worker
count, so it caps the achievable speedup. Measure it once at the corpus size
actually being run, 1 shard against 8, rather than fitting a curve across sizes.

Accuracy against MS MARCO qrels (MRR@10, nDCG@10) is worth doing once as a sanity
check on the merged index, on a 1xH100 pod rather than the 8-card one. It is not
an acceptance gate for a change that touches neither embedding nor ranking.

## Risks

The largest is that engine-slot collision does not explain the stall and rung 1
still fails, in which case the blocker list is wrong and the cause is unfound.
Rung 0 costs nothing and rung 1 costs $1.50, so finding out is cheap.

Second, per-GPU workers multiply shard count, and the merge has never run at 8 or
32 shards on real indexes.

Third, the throughput target assumes per-card rates hold when eight independent
processes contend for host CPU, page cache and PCIe. Change 2 exists for that,
but the size of the effect is unmeasured.
