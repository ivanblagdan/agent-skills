# Flow + shape map contract

## Required output sections
1) **Flow summary (5–12 steps)**
   - Entry -> transforms -> I/O -> side effects -> exit
   - Each step must include:
     - file path(s)
     - symbol(s) (function/type/method)
     - input shape -> output shape (names, not full schemas)
     - sync/async boundary markers (await, Task spawn, actor hop, queue hop)

2) **Shape map**
   - Canonical internal shapes (domain models) vs boundary shapes (DTO/view/persistence)
   - Where shapes are:
     - created
     - validated / decoded
     - serialized / encoded
     - transformed (mapping functions)
   - Call out redundant transforms (same mapping repeated)

3) **Concurrency + hot-path notes**
   - Concurrency boundaries and the primitives used (Swift actors/Task groups/queues, JS promises/workers/streams)
   - Shared mutable state and contention points (if any)
   - Hot path classification:
     - **Proven hot path**: only if backed by profiling/telemetry in-repo.
     - **Suspected hot path**: heuristic-based. Must list the heuristic used.

4) **Mermaid diagrams**
   - A **flowchart** for high-level dataflow
   - A **sequence diagram** focused on concurrency and parallel work
   - Apply Mermaid classes from `MERMAID_STYLE.md`

## Minimalism rule
- Collapse low-level helpers unless they are concurrency boundaries, shape boundaries, or hot-path suspects.


## Output format
- Present the user with points 1-3.
- Ask the user if they want the full report saved as markdown with embedded Mermaid diagrams (point 4). Suggest a default save path under the scan directory.
