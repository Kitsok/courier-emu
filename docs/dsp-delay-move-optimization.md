# Cache DSP delay-line region classification

Training-only A53 attribution identified native C5x execution as the largest
cost, including MADD, MACD and data-move operations. Those instructions read
an operand through the address-map cache, then repeatedly recomputed its
architectural region to decide whether the delay-line write was allowed.

DMOV, LTD, MACD and MADD now consult the same existing data-map entry when
it is valid. The entry's low counter bits distinguish DARAM and SARAM.
Dirty mappings retain the original classifier. Arithmetic, operand reads,
writes, tracing, counters and guest cycle formulas are unchanged. No new
cache or persistent core state is introduced.

`tools/benchmark_dsp_delay_moves.py` compares fresh cores using two million
modeled cycles per case after 10000 warmup cycles. Four pairs reverse order
on alternate repetitions. Timed work excludes setup and snapshot capture.
Snapshots compare architectural/serial state, map counters, operands and
write counts. A53 runs are pinned to CPU 3 under
`/tmp/courier-dsp-delay-a53`; its normal checkout is unchanged.

| Kernel | Notebook CPU reduction | A53 CPU reduction |
| --- | ---: | ---: |
| MADD / DARAM | 18.3% | 9.6% |
| MADD / SARAM | 15.7% | 12.8% |
| MACD / DARAM | 14.1% | 9.2% |
| DMOV / DARAM | 3.2% | 4.3% |
| LTD / SARAM | 5.0% | 6.3% |
| MADD / external data | 24.3% | 10.0% |

All measured snapshots match. The unchanged MADS control varies by +0.4%
CPU reduction on the notebook and -1.4% on A53; the primary-instruction
control varies by +0.7% and +2.0%, respectively. Small control differences
are not interpreted as general interpreter improvements.

The focused instruction/map suite passes 69 cases. New checks change CNF
and OVLY repeatedly, return to cached map configurations, and verify actual
writes and tracing on C51/C52/C53. C52 has no SARAM in this model, which is
explicitly covered. Eight-million-instruction standalone boot comparisons
match memory, registers, DSP/serial state, timers and interrupt state using
the untouched reference and candidate libraries.

Final local loopback peers both establish
`CONNECT 31200/ARQ/V34/LAPM/V42BIS` and exchange exact bidirectional data.
Experimental native pacing remains disabled. No new physical call was
made, no physical settings changed and no temperatures were sampled.

These are selected instruction kernels, not a full training replay or
whole-emulator performance result. The gains cannot be applied to the
entire C5x profile share; many other instructions and common execution
costs remain. The A53 real-time deficit is still unresolved. Full measured
repetitions and correctness evidence are in `docs/dsp-delay-move-results.json`.
