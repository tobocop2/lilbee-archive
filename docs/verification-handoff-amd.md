# Handoff: verifying lilbee on AMD hardware

Everything a fresh session needs to run the ROCm capture and land the result. Written because AMD is the last backend with no hardware behind it, and the machinery to test it is already built.

## Where things are

- Branch under test: `fix/ctx-slots-from-placed-device`, PR #620
- Capture script: `tools/wf/capture_engine_log.sh` on the `tools/gpu-verification-harness` branch
- What has been run so far: `docs/tested-gpus.md`
- Engine wheel indexes: `/cpu`, `/vulkan`, `/rocm`, `/cu125` under `https://lilbee.sh/`. There is no `/sycl`; it 404s

## Why AMD specifically

Three things are unverified and only AMD hardware can settle them.

**Device and host-allocator naming.** The readback decides what counts as GPU memory by excluding anything whose label starts with `CPU`/`AMX` or ends with `_Host`. That the pattern holds for AMD is read from ggml's source, never observed. It has been confirmed on CUDA (`CUDA_Host`) and Vulkan (`Vulkan_Host`). If ROCm words it differently, every AMD user sees a phantom overrun on every load.

**The same-rank backend tie-break.** CUDA, ROCm and HIP all sit at rank 3 in `_BACKEND_RANK`, so when two are present the winner is decided on memory. A fix landed on this branch to prefer dedicated bytes over a shared carveout, and it has no hardware behind it at all.

**Visibility variables.** `HIP_VISIBLE_DEVICES`, `ROCR_VISIBLE_DEVICES` and `GPU_DEVICE_ORDINAL` have a documented precedence order in `devices.py` that has never been exercised against a real ROCm runtime.

## Running the capture

On the rented box, one command:

```bash
curl -fsSL https://raw.githubusercontent.com/tobocop2/lilbee/tools/gpu-verification-harness/tools/wf/capture_engine_log.sh -o /tmp/cap.sh
ENGINE_INDEX=https://lilbee.sh/rocm/ TAG=mi300x OUT=/tmp/cap bash /tmp/cap.sh
```

It installs the ROCm engine into a throwaway virtualenv, loads a vision model so the projector case is covered too, prints every buffer line, and runs lilbee's own parser against the result.

### Gotchas already hit on other machines

- **Run it detached or in one foreground call.** A plain `ssh host "bash cap.sh"` dies with the connection if the caller backgrounds. Use `nohup ... &` and poll the log.
- **Minimal images lack `libgomp1` and `git`.** The script installs both where `apt-get` exists; on other distros install them first.
- **Check the glibc floor.** The published wheels need glibc 2.38 on some backends (see the open bug about the manylinux tag). Ubuntu 24.04 works; Debian 12 does not. The script says so rather than leaving a linker error.
- **The first `echo` comes after three pip installs.** An empty log for several minutes is normal, not a hang. `du -sh` the virtualenv to see progress.

## What to look for

The three answers that matter, in the script's own summary:

1. **Device labels.** Expect something like `ROCm0`. Whatever it is, it must match what `--device` and `--tensor-split` take, because the readback joins on that token.
2. **The host allocator.** Expect `ROCm_Host` or similar. It must be excluded from the GPU footprint. If the summary's `gpu footprint` includes it, that is the bug.
3. **The parser agreeing.** `per device` should list the card plus any host entries, and `gpu footprint` should be the card's buffers alone.

Sanity check the arithmetic by hand: the model buffer plus KV plus compute for the card should equal the footprint, and the model file size should roughly reconcile against the model buffers.

## Landing the result

1. Save the log as `tests/fixtures/engine-load-rocm.log` on the branch.
2. Add tests beside the existing ones in `tests/test_readback_regex.py`, following `TestARealVulkanLoad`: assert the parsed device set, assert the footprint excludes host entries, assert the build and load-finished markers.
3. Add a row to `docs/tested-gpus.md` under "Verified on real hardware" and a short "what it settled" paragraph. Move the ROCm row out of "Not yet tested".
4. If the naming differs from what the readback expects, that is a defect: fix `_HOST_PREFIXES` / `_HOST_SUFFIX` in `readback.py` with a failing test first.

## Method

Same rules as the rest of this work. Open the cited code at HEAD before changing it, write the failing test first, and if something does not reproduce say so with evidence rather than fixing it speculatively. Run the project gate (`make lint`, `make format-check`, `make typecheck`) plus the touched suites before committing. Do not run `make check` locally.

## Still open elsewhere

- Vulkan on AMD or Intel silicon. The MI300X box can cover the AMD half by installing the `/vulkan` wheel and repeating the capture, which is worth doing in the same session since the machine is already up.
- SYCL: blocked on a wheel that is not published.
- Two discrete cards from different vendors: not rentable.
- MIG: needs an A100 or H100 plus root.
