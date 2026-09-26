"""
ML configuration - single source of truth for training and inference settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# ponytail: full S&P 500 list collapsed into a helper so dev runs use a fast
# subset (~55 tickers = ~19s/epoch on MPS) and prod runs can opt-in to all 475
# via TRAINING_TICKERS env var. Re-expanding the inline list would be the same
# data — kept here as a single source of truth.
_ALL_SP500 = [
    "A",
    "AAL",
    "AAPL",
    "ABBV",
    "ABC",
    "ABT",
    "ACN",
    "ADBE",
    "ADI",
    "ADM",
    "ADP",
    "ADSK",
    "AEP",
    "AES",
    "AFL",
    "AIG",
    "AIZ",
    "AJG",
    "AKAM",
    "ALB",
    "ALGN",
    "ALL",
    "ALLE",
    "AMAT",
    "AMD",
    "AMGN",
    "AMP",
    "AMT",
    "AMZN",
    "ANET",
    "ANSS",
    "AON",
    "AOS",
    "APA",
    "APD",
    "APH",
    "ARE",
    "ATO",
    "AVB",
    "AVGO",
    "AVY",
    "AWK",
    "AXP",
    "AZO",
    "BA",
    "BAC",
    "BAX",
    "BBWI",
    "BBY",
    "BDX",
    "BEN",
    "BF.B",
    "BG",
    "BIIB",
    "BK",
    "BKNG",
    "BKR",
    "BLK",
    "BLL",
    "BMY",
    "BR",
    "BRK.B",
    "BRO",
    "BSX",
    "BWA",
    "BXP",
    "C",
    "CAG",
    "CAH",
    "CARR",
    "CAT",
    "CB",
    "CBOE",
    "CBRE",
    "CDNS",
    "CDW",
    "CE",
    "CEG",
    "CF",
    "CFG",
    "CHD",
    "CHRW",
    "CHTR",
    "CI",
    "CINF",
    "CL",
    "CLX",
    "CMA",
    "CMCSA",
    "CME",
    "CMG",
    "CMI",
    "CMS",
    "CNC",
    "CNP",
    "COF",
    "COO",
    "COP",
    "COST",
    "CPB",
    "CPRT",
    "CRM",
    "CRL",
    "CRWD",
    "CSCO",
    "CSGP",
    "CSX",
    "CTAS",
    "CTLT",
    "CTRA",
    "CTSH",
    "CTVA",
    "CVS",
    "CVX",
    "D",
    "DAL",
    "DD",
    "DE",
    "DECK",
    "DFS",
    "DG",
    "DGX",
    "DHI",
    "DHR",
    "DIS",
    "DLR",
    "DLTR",
    "DOV",
    "DPZ",
    "DRI",
    "DTE",
    "DUK",
    "DVN",
    "DXC",
    "DXCM",
    "EA",
    "EBAY",
    "ECL",
    "ED",
    "EFX",
    "EG",
    "EIX",
    "EL",
    "ELV",
    "EMN",
    "EMR",
    "ENPH",
    "EOG",
    "EQIX",
    "EQR",
    "EQT",
    "ES",
    "ESS",
    "ETN",
    "ETR",
    "ETSY",
    "EVRG",
    "EW",
    "EXC",
    "EXPD",
    "EXPE",
    "EXR",
    "F",
    "FANG",
    "FAST",
    "FCX",
    "FDX",
    "FE",
    "FFIV",
    "FI",
    "FIS",
    "FISV",
    "FITB",
    "FLR",
    "FLS",
    "FMC",
    "FOX",
    "FOXA",
    "FRT",
    "FSLR",
    "FTNT",
    "FTV",
    "GD",
    "GE",
    "GEHC",
    "GEN",
    "GILD",
    "GIS",
    "GL",
    "GLW",
    "GM",
    "GNRC",
    "GOOG",
    "GOOGL",
    "GPC",
    "GPN",
    "GRMN",
    "GS",
    "GWW",
    "HAL",
    "HAS",
    "HBAN",
    "HCA",
    "HD",
    "HES",
    "HIG",
    "HII",
    "HLT",
    "HOLX",
    "HON",
    "HPE",
    "HPQ",
    "HRL",
    "HSIC",
    "HST",
    "HSY",
    "HUM",
    "HWM",
    "IBM",
    "ICE",
    "IDXX",
    "IEX",
    "IFF",
    "ILMN",
    "INCY",
    "INTC",
    "INTU",
    "INVH",
    "IP",
    "IPG",
    "IQV",
    "IR",
    "IRM",
    "ISRG",
    "IT",
    "ITW",
    "IVZ",
    "J",
    "JBHT",
    "JCI",
    "JKHY",
    "JNJ",
    "JNPR",
    "JPM",
    "K",
    "KDP",
    "KEY",
    "KEYS",
    "KHC",
    "KIM",
    "KLAC",
    "KMB",
    "KMI",
    "KMX",
    "KO",
    "KR",
    "KVUE",
    "L",
    "LDOS",
    "LEN",
    "LH",
    "LHX",
    "LIN",
    "LKQ",
    "LLY",
    "LMT",
    "LNC",
    "LNT",
    "LOW",
    "LRCX",
    "LULU",
    "LUV",
    "LW",
    "LYB",
    "LYV",
    "MA",
    "MAA",
    "MAR",
    "MAS",
    "MCD",
    "MCHP",
    "MCK",
    "MDLZ",
    "MDT",
    "MET",
    "MGM",
    "MHK",
    "MKC",
    "MKTX",
    "MLM",
    "MMC",
    "MMM",
    "MNST",
    "MO",
    "MOH",
    "MOS",
    "MPC",
    "MPWR",
    "MRK",
    "MRNA",
    "MRO",
    "MS",
    "MSCI",
    "MSFT",
    "MSI",
    "MTB",
    "MTD",
    "MU",
    "NCLH",
    "NDAQ",
    "NDSN",
    "NEE",
    "NEM",
    "NFLX",
    "NI",
    "NKE",
    "NOC",
    "NOW",
    "NRG",
    "NSC",
    "NTAP",
    "NTRS",
    "NUE",
    "NVDA",
    "NVR",
    "NWS",
    "NWSA",
    "NXPI",
    "O",
    "ODFL",
    "OKE",
    "OMC",
    "ON",
    "ORCL",
    "ORLY",
    "OTIS",
    "OXY",
    "PANW",
    "PARA",
    "PAYC",
    "PAYX",
    "PCAR",
    "PCG",
    "PEAK",
    "PEP",
    "PFE",
    "PFG",
    "PG",
    "PGR",
    "PH",
    "PHM",
    "PKG",
    "PLD",
    "PM",
    "PNC",
    "PNR",
    "PNW",
    "PODD",
    "PPG",
    "PPL",
    "PRU",
    "PSA",
    "PSX",
    "PVH",
    "PWR",
    "PXD",
    "PYPL",
    "QCOM",
    "QRVO",
    "RCL",
    "REG",
    "REGN",
    "RF",
    "RHI",
    "RJF",
    "RL",
    "RMD",
    "ROK",
    "ROL",
    "ROP",
    "ROST",
    "RSG",
    "RTX",
    "SBAC",
    "SBUX",
    "SCHW",
    "SEE",
    "SHW",
    "SJM",
    "SLB",
    "SMCI",
    "SNPS",
    "SO",
    "SPG",
    "SPGI",
    "SRE",
    "STE",
    "STLD",
    "STT",
    "STX",
    "STZ",
    "SWK",
    "SWKS",
    "SYF",
    "SYK",
    "SYY",
    "T",
    "TAP",
    "TDG",
    "TDY",
    "TECH",
    "TEL",
    "TER",
    "TFC",
    "TFX",
    "TGT",
    "TJX",
    "TMO",
    "TMUS",
    "TPR",
    "TRGP",
    "TRMB",
    "TROW",
    "TRV",
    "TSCO",
    "TSLA",
    "TSN",
    "TT",
    "TTWO",
    "TXN",
    "TXT",
    "TYL",
    "UDR",
    "UHS",
    "ULTA",
    "UNH",
    "UNP",
    "UPS",
    "URI",
    "USB",
    "V",
    "VFC",
    "VICI",
    "VLO",
    "VMC",
    "VRSK",
    "VRSN",
    "VRTX",
    "VTR",
    "VTRS",
    "VZ",
    "WAB",
    "WAT",
    "WBA",
    "WBD",
    "WDC",
    "WEC",
    "WELL",
    "WFC",
    "WM",
    "WMB",
    "WMT",
    "WRB",
    "WRK",
    "WST",
    "WY",
    "WYNN",
    "XEL",
    "XOM",
    "XRAY",
    "XYL",
    "YUM",
    "ZBH",
    "ZBRA",
    "ZTS",
]

_DEV_SUBSET = _ALL_SP500[8::9]  # ~53 tickers, alphabetically spread across full S&P 500


def _train_tickers_env() -> list[str]:
    """Return ticker list: TRAINING_TICKERS env ("ALL" = full S&P 500) or dev subset."""
    env = os.environ.get("TRAINING_TICKERS")
    if env:
        if env.strip().upper() == "ALL":
            return list(_ALL_SP500)
        return [t.strip() for t in env.split(",") if t.strip()]
    return _DEV_SUBSET


@dataclass(frozen=True)
class MLConfig:
    """All ML training and inference configuration."""

    # Sequence settings
    SEQUENCE_LENGTH: int = int(os.environ.get("ML_SEQ_LEN", "30"))
    N_FEATURES: int = 17  # 13 V1 + vol_pct + 3 cross-sectional (excess_ret_1d/5d/21d vs SPY)
    BENCHMARK_TICKER: str = "SPY"  # Market benchmark for cross-sectional features

    # FLAT band = threshold_mult × σ_30d × √horizon. Selected on val, never test.
    VOL_LOOKBACK: int = 30
    THRESHOLD_MULT: float = (
        # Champion recipe (HPO phase-1 recipe + val-selected threshold; see
        # .optuna/best_hps.json). Old default 1.0 gave 32-36% dir acc.
        float(os.environ.get("ML_THRESHOLD_MULT", "2.0"))
    )
    FORECAST_HORIZON: int = 5  # N-day forward return (1=daily, 5=weekly, 21=monthly)

    # Causal volatility-percentile feature: expanding rank of rolling vol so each
    # day's percentile uses only history up to that day (no look-ahead).
    VOL_PCT_MIN_PERIODS: int = 60

    # Optional TRAIN-ONLY volatility regime filter. None = keep all windows
    # (val/test are never filtered — they must match the live distribution).
    VOL_FILTER_PERCENTILE: float | None = (
        float(os.environ["ML_VOL_FILTER"]) if "ML_VOL_FILTER" in os.environ else None
    )

    # Abstention decision rule: |p_up - p_down| < margin ⇒ predict FLAT (no trade).
    # Margin swept on val, chosen margin stored in the checkpoint.
    MARGIN_MIN: float = 0.0
    MARGIN_MAX: float = 0.8
    MARGIN_STEP: float = 0.05
    # Sweep guard: a margin is only eligible if >= this fraction of val
    # windows stay active — stops degenerate barely-trade-at-all winners.
    MARGIN_MIN_COVERAGE: float = 0.20

    # Drop tickers whose most recent data is older than this many days behind
    # the dataset's latest date (bulk snapshots include thousands of delisted
    # names that can never appear in the recent evaluation era).
    TICKER_MIN_RECENCY_DAYS: int = 90

    # Embargo between splits: drop train windows whose 5-day label window
    # overlaps val/test start. 2×h calendar days covers the label horizon;
    # shared pre-boundary feature content is not leakage (features are
    # computed from data strictly before the split date).
    EMBARGO_DAYS: int = FORECAST_HORIZON * 2

    # Transaction cost charged per non-flat position (round trip, basis points).
    COST_BPS_ROUND_TRIP: float = 10.0

    # Seeds to average test metrics over (mean ± CI for honest reporting).
    N_SEEDS: int = int(os.environ.get("ML_SEEDS", "5"))  # champion recipe = 5-seed prob ensemble

    # Model architecture — V1 LSTM only. V2 (Conv1D+BiLSTM+Attention+RegimeGate)
    # tested and caused gradient stall — 203k params could never escape uniform init.
    EMBED_DIM: int = int(os.environ.get("ML_EMBED_DIM", "16"))
    HIDDEN_DIM: int = int(
        os.environ.get("ML_HIDDEN_DIM", "112")
    )  # Optuna phase-1 champion HPs (backend/ml/.optuna/best_hps.json)
    N_LAYERS: int = 2  # 1 layer collapsed to majority-class prediction
    DROPOUT: float = float(
        os.environ.get("ML_DROPOUT", "0.45")
    )  # Optuna champion HPs (was 0.535 from the old tiny-data search)
    N_CLASSES: int = 3  # DOWN, FLAT, UP

    # Training (ML_EPOCHS env override exists for smoke runs)
    EPOCHS: int = field(default_factory=lambda: int(os.environ.get("ML_EPOCHS", "100")))
    BATCH_SIZE: int = 256  # 256 for MPS GPU memory efficiency
    LEARNING_RATE: float = float(
        # Optuna phase-1 champion HP (old tiny-data search picked 3.14e-4).
        os.environ.get("ML_LR", "8.652300790339428e-3")
    )
    # Cosine T_max; None → decay over the full epoch budget (early stopping
    # then strands the model at near-peak LR for its whole life).
    COSINE_T_MAX: int | None = int(t) if (t := os.environ.get("ML_T_MAX")) else None
    WEIGHT_DECAY: float = float(
        os.environ.get("ML_WD", "8.046267289217277e-05")
    )  # Optuna champion HP
    PATIENCE: int = (
        15  # early stopping after 15 epochs without val_dir_acc improvement (MIN_DELTA=0.5%)
    )
    MIN_DELTA: float = 5e-3  # minimum directional accuracy improvement to reset patience (0.5%)
    FOCAL_GAMMA: float = (
        float(os.environ.get("ML_FOCAL_GAMMA", "1.1879180415391768"))  # Optuna champion HP
    )
    # Ablation switch: "0" disables inverse-frequency class weighting (plain CE
    # behaviour when combined with ML_FOCAL_GAMMA=0).
    USE_CLASS_WEIGHTS: bool = os.environ.get("ML_CLASS_WEIGHTS", "1") != "0"
    # Margin sweep off by default — val-selected margins generalize worse than
    # plain argmax (winner's curse over margin candidates).
    MARGIN_SWEEP_ENABLED: bool = os.environ.get("ML_MARGIN_SWEEP", "0") == "1"

    # Split
    TRAIN_SPLIT: float = 0.7
    VAL_SPLIT: float = 0.15
    TEST_SPLIT: float = 0.15

    # Data
    TRAINING_TICKERS: list[str] = field(default_factory=lambda: _train_tickers_env())
    OHLCV_YEARS: int = field(
        default_factory=lambda: int(os.environ.get("ML_OHLCV_YEARS", "6"))
    )  # Training window — 6yr by default; raise via ML_OHLCV_YEARS after backfill

    # Inference fetch depth (rows): sized to cover OHLCV_YEARS so the causal
    # vol_pct expanding percentile at inference sees comparable history to training.
    PREDICTION_FETCH_LIMIT: int = field(
        default_factory=lambda: max(2100, int(os.environ.get("ML_OHLCV_YEARS", "6")) * 260)
    )

    # Paths
    MODEL_ARTIFACT_DIR: str = field(
        default_factory=lambda: os.environ.get("MODEL_ARTIFACT_DIR", "/model_artifacts/champion")
    )
    MLFLOW_TRACKING_URI: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5001")
    )
    DATABASE_URL: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://stocklens:stocklens@postgres:5432/stocklens"
        )
    )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Return a sync psycopg2-compatible DSN for pandas.read_sql.

        Strips the ``+asyncpg`` suffix from the async DSN.
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    # Inference
    MIN_OHLCV_DAYS: int = 60  # Minimum days needed for feature computation (30 window + padding)
    PREDICTION_CACHE_TTL: int = 21600  # 6 hours in seconds

    # Class names
    CLASS_NAMES: tuple[str, ...] = ("DOWN", "FLAT", "UP")


ML_CONFIG = MLConfig()
