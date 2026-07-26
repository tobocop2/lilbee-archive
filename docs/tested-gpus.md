# GPUs and backends tested

lilbee decides where a model goes by reading what the engine says about your hardware: what devices exist, how much memory each has, and what the engine actually allocated once it loaded. Every one of those answers is worded differently per backend, so each backend is verified on real silicon rather than inferred from the last one.

This page records what has been run and what has not. A backend listed as untested is not known to be broken; it is unverified, which is a different and more honest thing to say.

## Verified on real hardware

| GPU | Backend | Engine build | What it confirmed |
|-----|---------|--------------|-------------------|
| 2x NVIDIA A40 (46 GB) | CUDA | 9665 `e3a74b299` | Per-device buffer reporting on a tensor split, `CUDA0`/`CUDA1` labels, `CUDA_Host` excluded from device memory, cgroup memory limits honoured over `/proc/meminfo` |
| NVIDIA GTX 1070 Ti (8 GB) | Vulkan | 9665 `e3a74b299` | `Vulkan0` labels, `Vulkan_Host` excluded from device memory, vision projector accounting, Vulkan device enumeration and its crash isolation |
| Apple Silicon | Metal | 9310 `e2ef8fe42` | `MTL0` labels, unified-memory budgeting |
| Intel UHD (CometLake) + GTX 1650 Ti | Vulkan, hybrid | 9665 `e3a74b299` | Integrated adapters classified as shared memory, and a discrete card the loader cannot see still treated as dedicated |
| Intel Xeon Platinum 8481C | CPU | 9665 `e3a74b299` | Host-only load with no GPU present, `CPU`/`CPU_Mapped` attribution |

The captured logs behind these rows live on the `tools/gpu-verification-harness` branch, alongside the script that produced them.

### What the A40 pair settled

Two cards is where per-device accounting starts to matter: a plan can be right in total and wrong on one card, which is the failure that actually kills a load. The split reported `CUDA0` and `CUDA1` separately and the parser joined them to the planner's own per-device charges.

It also showed the driver and the engine disagree by design. `nvidia-smi` reported 480 and 492 MiB against the engine's 182.8 and 194.0 MiB for the same process. The gap is CUDA context overhead the engine never sees, so the two numbers answer different questions: the driver says what is unavailable to everyone else, the engine says what the model asked for.

### What the 1070 Ti settled

Vulkan is where every AMD and Intel GPU lands, so its wording matters well beyond NVIDIA. The engine names its pinned-host allocator `Vulkan_Host`, which lilbee must exclude from device memory or every Vulkan user sees a phantom overrun on every load.

A vision model on the same card settled a second question: a projector's weights appear in **no** buffer line at all. The engine reports them only as prose, so the estimate has to be corrected before it is compared, or every correctly-sized vision load reports a shortfall that is not there.

### What the hybrid laptop settled

The Vulkan loader can enumerate an integrated adapter alone while a dedicated card sits on the PCI bus, and reading that list as the whole truth marked a real 4 GB card as sharing system memory. On the machine tested, the discrete card had no driver claiming it; the same reading is produced by an Optimus setup that keeps the card idle until something asks through prime-run, and by any host where the vendor's Vulkan ICD is not active. What lilbee sees is identical in all three, which is why the fix keys on PCI presence rather than on the reason.

The integrated adapter also reported 11.5 GB of "VRAM", which is system RAM it can borrow rather than memory it owns. Both halves matter: an integrated GPU must be budgeted against the host's memory, and a discrete one must not be, and on this machine the two live side by side.

## Not yet tested

| Backend | Status |
|---------|--------|
| ROCm (AMD Instinct, Radeon) | No hardware run. Device naming, `ROCm_Host`, and the same-rank backend tie-break are all unverified |
| Vulkan on AMD or Intel silicon | No hardware run. Vulkan itself is verified, but only on an NVIDIA ICD |
| SYCL (Intel Arc, Max) | No engine wheel is published for SYCL, so this cannot be tested on any hardware today |
| CANN (Huawei Ascend) | No hardware run |
| Mixed-vendor host with two discrete cards | Partly covered. A hybrid Intel plus NVIDIA laptop is verified above; two discrete cards from different vendors in one machine is not, and cloud providers do not sell it |
| MIG-partitioned NVIDIA | No hardware run. Needs an A100 or H100 plus root to partition it |
| AMX-enabled CPU build | Not reachable. The published CPU wheel is an AVX2 baseline with AMX compiled out, verified on a Xeon that has the instructions |

## Reproducing any of these

`tools/wf/capture_engine_log.sh` on the `tools/gpu-verification-harness` branch takes one environment variable and does the rest: installs the backend's engine into a throwaway virtualenv, loads a vision model so the projector case is covered, prints every buffer line, and runs lilbee's own parser against the result.

```
ENGINE_INDEX=https://lilbee.sh/vulkan/ TAG=my-card bash capture_engine_log.sh
```

Wheel indexes are `/cpu`, `/vulkan`, `/rocm` and `/cu125`. What comes back is the log plus the three answers that matter: what the engine calls its devices, what it calls its pinned-host allocator, and whether lilbee agrees with both.

Captures from hardware not listed above are welcome, and the untested rows are the useful ones.
