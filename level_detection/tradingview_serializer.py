"""
TradingView Serializer Module.

Converts detected BSU levels to TradingView-compatible string format
for use with Pine Script indicators (Hybrid Architecture approach).
"""

import logging
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


class TradingViewSerializer:
    """
    Serialize detected levels for TradingView Pine Script input.

    Output Format: "Price:Type:Meta,Price:Type:Meta,..."

    Type Encoding:
        R = Resistance
        S = Support

    Meta Encoding:
        M = Mirror level (highest priority - acts as both S/R)
        P = Paranormal bar / Model #4 candidate (Score >= threshold)
        N = Normal level
    """

    # Score threshold for paranormal classification
    PARANORMAL_SCORE_THRESHOLD: int = 30

    @classmethod
    def serialize_levels(
        cls,
        df_levels: pd.DataFrame,
        ticker: Optional[str] = None,
        max_levels: Optional[int] = None,
        sort_by_score: bool = True,
    ) -> str:
        """
        Convert levels DataFrame to TradingView string format.

        Args:
            df_levels: DataFrame from BSU detection with columns:
                       [Price, Type, Score, IsMirror/Is_Mirror, ...]
            ticker: Filter for specific ticker (optional).
            max_levels: Maximum number of levels to include (optional).
            sort_by_score: If True, sort by score descending.

        Returns:
            String formatted for TradingView input.text_area()
            Example: "150.25:R:P,148.10:S:N,155.00:R:M"
        """
        if df_levels.empty:
            logger.warning("Empty DataFrame provided, returning empty string")
            return ""

        df = df_levels.copy()

        # Filter by ticker if specified
        if ticker:
            ticker = ticker.upper()
            if "Ticker" in df.columns:
                df = df[df["Ticker"] == ticker]
            if df.empty:
                logger.warning(f"No levels found for ticker: {ticker}")
                return ""

        # Sort by score if requested
        if sort_by_score and "Score" in df.columns:
            df = df.sort_values("Score", ascending=False)

        # Limit number of levels
        if max_levels:
            df = df.head(max_levels)

        level_strings = []

        for _, row in df.iterrows():
            price = row["Price"]

            # Type encoding
            level_type = cls._encode_type(row["Type"])

            # Meta encoding
            meta = cls._encode_meta(row)

            level_strings.append(f"{price:.2f}:{level_type}:{meta}")

        result = ",".join(level_strings)
        logger.info(f"Serialized {len(level_strings)} levels")

        return result

    @classmethod
    def _encode_type(cls, type_value: str) -> str:
        """
        Encode level type to single character.

        Args:
            type_value: Type string from DataFrame ('R', 'S', 'M',
                       'Resistance', 'Support', 'Mirror')

        Returns:
            'R' for Resistance, 'S' for Support
        """
        type_upper = str(type_value).upper()

        if type_upper in ("R", "RESISTANCE"):
            return "R"
        elif type_upper in ("S", "SUPPORT"):
            return "S"
        elif type_upper in ("M", "MIRROR"):
            # Mirror levels are encoded based on their primary function
            # The meta field will indicate it's a mirror
            return "R"  # Default to resistance for mirror levels
        else:
            logger.warning(f"Unknown level type: {type_value}, defaulting to 'R'")
            return "R"

    @classmethod
    def _encode_meta(cls, row: pd.Series) -> str:
        """
        Encode level metadata to single character.

        Priority: Mirror > Paranormal > Normal

        Args:
            row: DataFrame row with level data

        Returns:
            'M' for Mirror, 'P' for Paranormal, 'N' for Normal
        """
        # Check for mirror level (highest priority)
        is_mirror = row.get("IsMirror", row.get("Is_Mirror", False))
        if is_mirror:
            return "M"

        # Check for paranormal/high-score level
        score = row.get("Score", 0)
        is_paranormal = row.get("IsParanormal", row.get("Is_Paranormal", False))

        if is_paranormal or score >= cls.PARANORMAL_SCORE_THRESHOLD:
            return "P"

        # Normal level
        return "N"

    @classmethod
    def deserialize_levels(cls, serialized_string: str) -> List[dict]:
        """
        Parse TradingView string format back to level data.

        Args:
            serialized_string: String in format "Price:Type:Meta,..."

        Returns:
            List of dictionaries with level data.
        """
        if not serialized_string or not serialized_string.strip():
            return []

        levels = []

        for level_str in serialized_string.split(","):
            level_str = level_str.strip()
            if not level_str:
                continue

            parts = level_str.split(":")
            if len(parts) != 3:
                logger.warning(f"Invalid level format: {level_str}")
                continue

            try:
                price = float(parts[0])
                level_type = parts[1].upper()
                meta = parts[2].upper()

                levels.append({
                    "price": price,
                    "type": "Resistance" if level_type == "R" else "Support",
                    "is_mirror": meta == "M",
                    "is_paranormal": meta == "P",
                    "meta": meta,
                })
            except ValueError as e:
                logger.warning(f"Error parsing level '{level_str}': {e}")
                continue

        return levels

    @classmethod
    def save_to_file(
        cls,
        serialized_string: str,
        ticker: str,
        output_dir: Union[str, Path] = "output",
    ) -> Path:
        """
        Save serialized string to file.

        Args:
            serialized_string: The TradingView-formatted string.
            ticker: Ticker symbol for filename.
            output_dir: Output directory path.

        Returns:
            Path to the saved file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"levels_{ticker.upper()}_tradingview.txt"
        filepath = output_dir / filename

        with open(filepath, "w") as f:
            f.write(serialized_string)

        logger.info(f"Saved TradingView levels to: {filepath}")
        return filepath

    @classmethod
    def load_from_file(cls, filepath: Union[str, Path]) -> str:
        """
        Load serialized string from file.

        Args:
            filepath: Path to the file.

        Returns:
            The serialized string content.
        """
        filepath = Path(filepath)

        with open(filepath, "r") as f:
            content = f.read().strip()

        logger.info(f"Loaded TradingView levels from: {filepath}")
        return content

    @classmethod
    def generate_pine_script_array(
        cls,
        df_levels: pd.DataFrame,
        ticker: Optional[str] = None,
        array_name: str = "levels",
    ) -> str:
        """
        Generate Pine Script array declaration for levels.

        This is an alternative output format that creates a Pine Script
        array directly, useful for embedding in indicator code.

        Args:
            df_levels: DataFrame with level data.
            ticker: Optional ticker filter.
            array_name: Name for the Pine Script array.

        Returns:
            Pine Script code declaring the levels array.
        """
        if df_levels.empty:
            return f"var float[] {array_name} = array.new_float(0)"

        df = df_levels.copy()

        if ticker and "Ticker" in df.columns:
            df = df[df["Ticker"] == ticker.upper()]

        prices = df["Price"].tolist()

        # Format as Pine Script array
        price_strings = [f"{p:.2f}" for p in prices]
        array_init = ", ".join(price_strings)

        pine_code = f"""// Auto-generated levels for {ticker or 'all tickers'}
var float[] {array_name} = array.from({array_init})
"""
        return pine_code

    @classmethod
    def format_summary(
        cls,
        df_levels: pd.DataFrame,
        ticker: Optional[str] = None,
    ) -> str:
        """
        Generate human-readable summary of levels.

        Args:
            df_levels: DataFrame with level data.
            ticker: Optional ticker filter.

        Returns:
            Formatted summary string.
        """
        if df_levels.empty:
            return "No levels detected."

        df = df_levels.copy()

        if ticker and "Ticker" in df.columns:
            df = df[df["Ticker"] == ticker.upper()]

        total = len(df)
        resistance = len(df[df["Type"].isin(["R", "Resistance"])])
        support = len(df[df["Type"].isin(["S", "Support"])])
        mirror = len(df[df["Type"].isin(["M", "Mirror"])])

        # Count by meta type
        mirror_count = df.get("IsMirror", df.get("Is_Mirror", pd.Series([False] * len(df)))).sum()
        paranormal_count = df.get("IsParanormal", df.get("Is_Paranormal", pd.Series([False] * len(df)))).sum()

        summary = f"""
Level Summary{f' for {ticker}' if ticker else ''}
{'=' * 40}
Total Levels: {total}
├── Resistance: {resistance}
├── Support: {support}
└── Mirror: {mirror}

Meta Classification:
├── Mirror (M): {mirror_count}
├── Paranormal (P): {paranormal_count}
└── Normal (N): {total - mirror_count - paranormal_count}

Score Range: {df['Score'].min():.0f} - {df['Score'].max():.0f}
Average Score: {df['Score'].mean():.1f}
"""
        return summary.strip()
