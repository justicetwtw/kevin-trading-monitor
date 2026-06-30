# Kevin Trading Monitor — Project Context v4.2

This repository is the single source of truth for the Invest project workflow.

## Persistent workflow requirements

- Always read this repository before discussing the model.
- Telegram alerts and future dashboards are decision-support tools.
- Reduce noisy alerts by separating Red Alert, Market Brief, and Noise Digest.
- Keep watchlists, strategy rules, model assumptions, and implementation roadmap in repo files rather than only in chat memory.

## Model upgrade direction

- Industry-first screening: identify the right industry cycle, then filter for quality leaders and high-beta representatives.
- Policy-event monitoring: public posts, official policy, government procurement, regulatory changes, and funding programs should be structured into event objects with direction, confidence, materiality, affected themes, affected symbols, and half-life.
- Social/KOL monitoring: X, FB communities, and important investors should feed a future dashboard with deduplication and relevance scoring.
- Options-data upgrade: evaluate paid data sources for unusual options activity, volume, OI, IV rank, skew, and support/resistance inference.
- Momentum overlay: add momentum factors as timing signals, not as a replacement for fundamental and industry thesis.

## Highest-priority themes

- Memory / storage / AI infrastructure.
- Optical networking / CPO.
- MLCC, passive components, power semiconductor.
- AI capex beneficiaries and AI capex risk.
- Government procurement and national-security beneficiaries.

## Core watchlist baseline

### Memory / storage
```text
MU, SNDK, WDC, STX, SIMO, DRAM, RAM, MUU, WDCX, SNXX, 000660, 285A, RMBS
```

### Large tech / semiconductor / related ETFs
```text
TSM, TSMX, GOOG, GGLL, AAPL, AMD, AMDL, INTL, INTW, SPCY, SPCF,
TSLA, TSLL, TSLT, MSFT, MSFU, ORCL, META, METU, FBL,
SMH, SOXX, SOXL, AMZN, AMZZ, AVGO, AVGX, NVDA, NVDL,
EWY, KORU, JBL, DELL, IBM, QCOM, VT, VTI, QQQ
```

### Optical / networking / CPO
```text
MRVL, MVLL, COHR, AAOI, ALAB, AXTI, AXTX, TSEM, GFS, LITE, LITX, GLW, NOK, FOTD, CRDO, DD
```

### AI infrastructure / equipment
```text
ARM, ARMG, CAT, VRT, AMAT, ASML, LRCX, LRCU, KLAC, NBIS, APH, ANET, CRWV, RBRK
```

### Defense / government procurement
```text
ONDS, PLTR, KTOS, SHLD, AVAV, LMT, RTX
```

### Energy / nuclear / grid / oil & gas
```text
BE, ETN, GEV, VST, EOSE, CEG, OKLO, LEU, SMR, NNE, MIR, FLS, SO, NEE, VLO, XOM, USO, CVX
```

### Taiwan ETFs and semiconductor supply chain
```text
00981A, 00991A, 0050, 3665, 00631L,
2330, 2454, 8299, 3017, 6669, 2345, 6223, 2308, 6274
```

### Space / metals / commodities / crypto indicators
```text
ASTS, RKLB, PPA, UFO, NASA,
CCJ, MP, FCX, GLD, GDX, SLV, SILJ, SIVR, CPER, COPX, URNM, REMX, UEC, URA, USAR, UUUU,
CPC, CPCI, VIX, PCCE, CL1!, USOIL, BTCUSD, ETHUSD, ADAUSD
```
