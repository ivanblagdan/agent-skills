# Mermaid style contract

Use these class definitions for consistency across skills:

```mermaid
%% Apply classes with: class NodeId hot;
classDef hot fill:#ffe6e6,stroke:#ff4d4d,stroke-width:2px;
classDef async fill:#e6f0ff,stroke:#2f6fed,stroke-width:2px;
classDef boundary fill:#fff7e6,stroke:#f0a500,stroke-width:2px;
classDef data fill:#e6fff2,stroke:#2dbf6a,stroke-width:2px;
classDef io fill:#f2e6ff,stroke:#8a2be2,stroke-width:2px;
```

Conventions:
- `hot`: suspected or known hot path nodes.
- `async`: concurrency boundaries, parallel work, actor hops, task creation.
- `boundary`: trust/shape boundaries (decode/encode/validate), API boundaries.
- `data`: core data shapes / canonical models.
- `io`: external I/O (network, DB, filesystem).
