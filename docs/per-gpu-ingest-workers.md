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

## Changes: one, plus configuration

Almost everything the architecture needs already exists as configuration. One
thing does not, and it is a race rather than a setting.

### The one code change: deterministic port ranges

`_pick_free_ports` claims a port by binding a socket and releases it before
llama-server binds, so workers starting together can pick the same port. Measured
on 2xH100 over the same corpus, changing only the launch stagger:

| launch | per-card GPU | end-to-end |
|---|---|---|
| simultaneous | 8% / 87% | 53.9 docs/s |
| 15s stagger | **90% / 88%** | **98.5 docs/s** |

The 8%/87% signature is one worker driving the other's engine. A stagger narrows
the window rather than closing it, and it scales badly: eight workers at 15s is
two minutes of dead time and still probabilistic.

Give each worker a disjoint port range derived from something it already knows,
its worker index or a hash of `LILBEE_ENGINE_DIR`. No coordination, no
reservation file, collisions impossible by construction. Roughly twenty lines in
the port picker.

### Everything else is configuration

Four environment variables per worker, all verified:

```bash
CUDA_VISIBLE_DEVICES=$i               # masks the device view
LILBEE_DATA=/root/w$i                 # private data root
LILBEE_ENGINE_DIR=/root/w$i/engine    # private engine slot
LILBEE_INGEST_WORKERS=$((CORES / N))  # divides the planning pool
```

**Engine identity** was the one true blocker. `machine_engine_dir()`
(`runtime/engine_lock.py:60`) returns `default_state_dir()/engine`, ignores
`LILBEE_DATA`, and is documented as "the per-OS-user engine slot every lilbee
process scans first"; `find_live_state` then globs it for any pid's state file so
"a guest lilbee can bind to this live fleet". Pinned workers therefore adopted
worker 0's fleet, which is exactly the observed one-engine-seven-idle-cards.
`LILBEE_ENGINE_DIR` (`ENGINE_DIR_ENV`, same file, line 28) overrides it. Measured:
two data roots collide on one slot; with the override set they do not.

**Pool sizing** is already overridable. `resolve_process_count`
(`workers.py:100`) reads `active_config().ingest_processes` and `_plan_workers`
(`pipeline.py:336`) reads `active_config().ingest_workers`, which otherwise
defaults to `available_cpu_count()` — so N pinned workers would each size a pool
to the whole box. Setting the existing override per worker closes it; no new knob.

What is left is a product question, not a blocker: should lilbee *derive* a
private engine slot and pool share when it detects it is pinned, rather than
requiring an operator to know four environment variables?

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

### Planning cost, resolved

Planning is streamed, not a preamble. #609 made the plan stream so embedding
starts before the corpus is hashed: `_StreamedPlan` accumulates across shards,
`_shard_bounds` ramps 256 to 4096, and `_ResultFeed` is a pull-based source where
"the collector waits on the planner only when it has nothing left to run".
Hashing overlaps GPU work.

That also means the plan-progress line cannot be read as planning cost. It
reports files planned over wall-clock, and because the stream is pull-driven,
planning advances only as fast as embedding consumes it — a low rate can mean
embedding is not pulling. The 16-30 files/s seen in the failed run is not
evidence that planning is slow.

A first ingest does hash every file (`pipeline.py:312`; a fresh index has no
stored stat, so the fast path is skipped), and the pass runs across
`available_cpu_count()`. lilbee's own note says it "can run for tens of minutes
on a multi-million-file corpus" — total hashing work overlapped with embedding,
not blocking time.

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

**Rung 1, ~$2. Passed.** Two pinned workers on 2xH100 over 20k passages. Both
landed 10,000 rows with zero failures, each took its own engine dir, and GPU
utilisation during the embed window was 92%/92% at 119.0 docs/s aggregate — 59.5
per card, exactly the rate a single card reaches alone. Per-GPU workers scale
linearly.

The same run reported 15.0 docs/s end-to-end with embedding at 13% of wall clock.
**Both figures are artifacts of the harness**, which dealt every worker's files
into one directory where the corpus uses 1000 per directory. The numbers do not
reconcile otherwise: 4xH100 ingested 80k in 494s, against 1334s for 20k here. The
mechanism is plan-stream starvation — with streaming, an idle GPU means no
planned files were available, and discovery's stat scan over a 10,000-entry
directory could not feed it.

**Rung 1b, ~$2. Passed.** Bucketing 1000 files per directory cut wall clock from
1334s to 401s and moved embedding from 13% to 82% of the run. Planning was never
the problem; the streamed plan works, and the earlier layout starved it.

**Rung 1c/1d, ~$4. Found the second blocker.** 1c dropped the launch stagger and
measured 8%/87% per-card at 53.9 docs/s. 1d restored it and measured 90%/88% at
98.5 docs/s over the same corpus, changing nothing else. That isolates the port
race above, and 98.5 on two cards is 1.66x the 59.5 single-card rate.

**Rung 2, the full sweep**, next: N = 1, 2, 4, 8 on one 8xH100 host with the
stagger (or the port fix) and a repeat at the best N. There is now a mechanism
explaining why it should scale, which there was not before.

Use the 8B production model throughout, not a small one: a 0.6B embedder on fast
cards is client-bound rather than GPU-bound, and generalising across regimes is
how three earlier proposals went wrong.

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
