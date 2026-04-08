"""Unit tests for the article/narrative relevance scoring module."""

import pytest
from mctrend.ingestion.relevance import (
    score_article_relevance,
    score_narrative_relevance,
    _compute_relevance,
    _term_in_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SAT = 1.5
_DEFAULT_VETO_THRESHOLD = 0.15
_DEFAULT_VETO_PENALTY = 0.02


def article_score(title: str, description: str = "", source_name: str = "") -> float:
    return score_article_relevance(
        title, description, source_name,
        positive_saturation=_DEFAULT_SAT,
        veto_override_threshold=_DEFAULT_VETO_THRESHOLD,
        veto_penalized_score=_DEFAULT_VETO_PENALTY,
    )


def narrative_score(anchor_terms: list[str], description: str = "", source_names: list[str] | None = None) -> float:
    return score_narrative_relevance(
        anchor_terms, description, source_names,
        positive_saturation=_DEFAULT_SAT,
        veto_override_threshold=_DEFAULT_VETO_THRESHOLD,
        veto_penalized_score=_DEFAULT_VETO_PENALTY,
    )


# ---------------------------------------------------------------------------
# TestTermMatching
# ---------------------------------------------------------------------------


class TestTermMatching:
    def test_whole_word_match_only(self):
        """Single-word terms should not match partial strings."""
        # "sol" should not match "absolutely"
        assert not _term_in_text("sol", "absolutely no mention here")

    def test_whole_word_match_positive(self):
        """Single-word terms should match when present as a word."""
        assert _term_in_text("sol", "the sol price dropped today")

    def test_phrase_match(self):
        """Multi-word phrases should match as substring."""
        assert _term_in_text("pump.fun", "check out pump.fun for tokens")

    def test_phrase_no_match(self):
        """Phrases that don't appear should not match."""
        assert not _term_in_text("pump.fun", "this article is about basketball")


# ---------------------------------------------------------------------------
# TestCryptoArticles — articles that SHOULD pass the relevance gate
# ---------------------------------------------------------------------------


class TestCryptoArticles:
    def test_memecoin_article_passes(self):
        score = article_score(
            "New memecoin launches on Solana via pump.fun",
            "Traders are rushing to buy the new token with growing liquidity",
        )
        assert score >= 0.20, f"Expected crypto article to pass, got {score}"

    def test_solana_token_article_passes(self):
        score = article_score(
            "Solana memecoin token MOONDOG gains 400% on launch",
            "The cryptocurrency launched on pump.fun with 500 holders on day one",
        )
        assert score >= 0.20

    def test_defi_article_passes(self):
        score = article_score(
            "DeFi protocol adds new token launch support",
            "Web3 ecosystem expanding with new blockchain liquidity pools",
        )
        assert score >= 0.20

    def test_bitcoin_article_passes(self):
        score = article_score(
            "Bitcoin hits new all-time high amid crypto market rally",
            "Trading volume surges across cryptocurrency exchanges",
        )
        assert score >= 0.20

    def test_pumpfun_platform_article_passes(self):
        score = article_score(
            "pump.fun crosses 1 million token launches",
            "The Solana-based token launch platform continues to grow",
        )
        assert score >= 0.20

    def test_nft_article_passes(self):
        score = article_score(
            "NFT collection sold for 500 ETH in blockchain auction",
            "Digital asset marketplace sees record trading volume",
        )
        assert score >= 0.20


# ---------------------------------------------------------------------------
# TestIrrelevantArticles — articles that SHOULD be blocked
# ---------------------------------------------------------------------------


class TestIrrelevantArticles:
    def test_sports_championship_blocked(self):
        score = article_score(
            "NBA championship game draws record viewers",
            "The basketball playoffs concluded with an exciting final",
        )
        assert score <= _DEFAULT_VETO_PENALTY + 0.01, f"Expected sports article to be blocked, got {score}"

    def test_politics_election_blocked(self):
        score = article_score(
            "Senate votes on new election reform legislation",
            "The congress passed a bill approved by the president",
        )
        assert score <= _DEFAULT_VETO_PENALTY + 0.01, f"Expected politics article to be blocked, got {score}"

    def test_entertainment_oscars_blocked(self):
        score = article_score(
            "Oscars 2025: Best Picture winner announced on red carpet",
            "The academy awards ceremony featured box office stars",
        )
        assert score <= _DEFAULT_VETO_PENALTY + 0.01, f"Expected entertainment article to be blocked, got {score}"

    def test_generic_cooking_blocked(self):
        score = article_score(
            "Top recipe for summer food festival season",
            "Cooking show highlights new restaurant review trends",
        )
        assert score <= _DEFAULT_VETO_PENALTY + 0.01, f"Expected cooking article to be blocked, got {score}"

    def test_nfl_football_blocked(self):
        score = article_score(
            "NFL Super Bowl touchdown record broken in playoffs",
            "The quarterback threw a home run equivalent in championship",
        )
        assert score <= _DEFAULT_VETO_PENALTY + 0.01


# ---------------------------------------------------------------------------
# TestVetoOverride — crypto-adjacent sports/celeb articles should pass
# ---------------------------------------------------------------------------


class TestVetoOverride:
    def test_athlete_launches_token_passes(self):
        """An athlete launching a Solana token should override the sports veto."""
        score = article_score(
            "NBA star launches Solana memecoin token on pump.fun",
            "The cryptocurrency was created on blockchain and reached 1000 holders",
        )
        # High crypto signal should override the sports veto
        assert score >= 0.20, f"Athlete token article should pass, got {score}"

    def test_celebrity_token_passes(self):
        """A celebrity launching a crypto token should pass."""
        score = article_score(
            "Celebrity launches token on Ethereum blockchain",
            "The crypto asset is available to trade with liquidity locked",
        )
        assert score >= 0.20


# ---------------------------------------------------------------------------
# TestNarrativeScoring
# ---------------------------------------------------------------------------


class TestNarrativeScoring:
    def test_crypto_anchor_terms_score_high(self):
        score = narrative_score(
            anchor_terms=["SOLANA", "MEMECOIN", "PUMP"],
            description="Solana memecoin pump token",
        )
        assert score >= 0.15

    def test_non_crypto_terms_score_low(self):
        score = narrative_score(
            anchor_terms=["BASKETBALL", "CHAMPIONSHIP", "PLAYOFFS"],
            description="NBA championship game",
        )
        assert score <= 0.05

    def test_veto_override_with_crypto_terms(self):
        score = narrative_score(
            anchor_terms=["TOKEN", "CRYPTO", "SOLANA"],
            description="NBA player launches token on Solana blockchain",
        )
        assert score >= 0.15

    def test_source_names_contribute_to_score(self):
        """Source names from crypto outlets can help borderline narratives pass."""
        score_with_source = narrative_score(
            anchor_terms=["MARKET", "LAUNCH"],
            description="new token on chain",
            source_names=["coindesk.com", "cointelegraph.com"],
        )
        score_without_source = narrative_score(
            anchor_terms=["MARKET", "LAUNCH"],
            description="new token on chain",
            source_names=[],
        )
        # With crypto source names the score should be higher or equal
        assert score_with_source >= score_without_source

    def test_empty_narrative_scores_zero(self):
        score = narrative_score(anchor_terms=[], description="")
        assert score == 0.0

    def test_saturation_caps_at_one(self):
        """Even with many crypto terms, score is capped at 1.0."""
        score = narrative_score(
            anchor_terms=["CRYPTO", "TOKEN", "SOLANA", "MEMECOIN", "PUMP", "DEFI", "NFT", "WEB3"],
            description="bitcoin ethereum blockchain trading exchange liquidity wallet",
        )
        assert score <= 1.0


# ---------------------------------------------------------------------------
# TestConfigurableThresholds
# ---------------------------------------------------------------------------


class TestConfigurableThresholds:
    def test_lower_saturation_increases_score(self):
        """Lower positive_saturation means easier to reach max score."""
        text = "solana token"
        score_tight = _compute_relevance(text, positive_saturation=3.0,
                                         veto_override_threshold=0.15, veto_penalized_score=0.02)
        score_loose = _compute_relevance(text, positive_saturation=0.5,
                                         veto_override_threshold=0.15, veto_penalized_score=0.02)
        assert score_loose > score_tight

    def test_high_veto_override_threshold_blocks_crypto_adjacent(self):
        """With a very high veto threshold, even moderate crypto signals get vetoed."""
        score = _compute_relevance(
            "nfl championship token launch",
            positive_saturation=1.5,
            veto_override_threshold=0.99,  # almost impossible to override
            veto_penalized_score=0.02,
        )
        # NFL is a veto term; even "token launch" won't save it with threshold=0.99
        assert score == pytest.approx(0.02)

    def test_veto_penalty_is_configurable(self):
        """Custom veto penalty is applied when veto fires."""
        score = _compute_relevance(
            "nba playoffs championship basketball",
            positive_saturation=1.5,
            veto_override_threshold=0.15,
            veto_penalized_score=0.05,
        )
        assert score == pytest.approx(0.05)
