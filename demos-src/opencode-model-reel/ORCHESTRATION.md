# opencode model reel: pod orchestration

What runs on the RunPod 2xH200 box to produce the opencode agentic-coding demos,
and how it is captured. This doc exists so the running pod and the repo stay in
sync: what executes on the pod is the code in this directory.

## Pipeline

1. **`pod_bootstrap.sh`** (model-independent, runs once on a fresh pod)
   System deps -> uv -> clone lilbee (`feat/local-model-api`) -> `uv sync` ->
   build a CUDA `llama-server` from source (no prebuilt CUDA Linux binary ships
   upstream). Detached in the `work` tmux session, logs to `/root/run.log`, ends
   on the `BUILD_STAGE_DONE` marker.

2. **`giant_demo.sh <family> <gguf>`** (per model)
   Warms the giant on `llama-server --jinja` (native tool calls) at `:8090`,
   indexes a real codebase into lilbee, and starts `lilbee serve /mcp` at `:8080`
   for `lilbee_search`. opencode runs in an **empty** project dir with an
   `AGENTS.md` grounding directive, so the agent **must** use `lilbee_search` to
   see the code. Measures the real cold-start time for an honest intro card.

3. **`giant_demo.tape.tmpl` + `build_reel.sh`** (record + assemble)
   The tape drives the **real** opencode TUI against the warm server: type the
   prompt, watch `lilbee_search` fire, watch the answer stream live. `build_reel.sh`
   prepends a short labeled, time-compressed cold-start card built from the
   measured load time (never real-time dead air), derives gif + mp4, then runs the
   review gate.

4. **`review_demo.py`** (timeline audit gate)
   Extracts evenly spaced frames across the whole runtime and runs an mpdecimate
   "dead-screen" tripwire (a recording dominated by a static cold-start/spinner
   screen fails). The frames are then eyeballed: prompt visible, real TUI working,
   `lilbee_search` fired, file/answer present, good result, zero error frames.

## Capture: on the pod (VHS works here)

Everything runs on the pod, VHS included. The old "VHS captures 0 frames on the pod"
problem had two mundane causes, both fixed in `pod_bootstrap.sh`:

1. **Outdated ttyd.** apt ships ttyd 1.6.3; VHS rejects anything below 1.7.2
   (`ttyd version (1.6.3) is out of date, VHS requires 1.7.2`). The bootstrap
   installs the 1.7.7 release binary.
2. **Absolute `Output` path.** VHS's parser chokes on `Output /root/x.gif`
   (`Invalid command: root`). Tapes use a **relative** Output and VHS runs from the
   output dir (`build_reel.sh` handles this).

With those, `VHS_NO_SANDBOX=true vhs tape` renders real multi-frame output on the
box. No SSH tunnel, no RunPod proxy, no Mac, no public exposure.

## Honesty rules baked in

- Cold start is **measured** (`/health` 200 = weights resident), shown as a
  labeled fast-forwarded card, never faked or hidden as dead air.
- The session is **real**: the written file exists on disk afterward, the
  `lilbee_search` call appears in the lilbee server log, and the answer cites real
  retrieved files. A demo that can't show all three does not ship.
- Every demo is reviewed frame-by-frame across its full timeline before it goes in
  the reel. No `cat`/`sed`/`tree` shell replays. Ever.

## Placement

- This orchestration **code** lives on the `demo-reel/opencode-model-matrix` branch.
- The **rendered reel** (gif/mp4 + site) publishes to **gh-pages**.

## Status

- `pod_bootstrap.sh`: CUDA llama-server built; VHS confirmed rendering real frames on
  the pod (ttyd 1.7.7 + relative Output). VHS step folded into the bootstrap.
- `giant_demo.sh` / `build_reel.sh`: paths reconciled to `/root/llama.cpp` +
  `/root/lilbee`; relative-Output fix applied. Per-model serve + index + record next.
